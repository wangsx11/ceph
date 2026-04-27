// native_rdma data-plane entry point.
// W2: full OOB handshake + real RDMA WRITE/READ + RDMA SEND heartbeat + real KV.

#include "common/logger.h"
#include "common/time_util.h"
#include "rdma/rdma_core.h"
#include "rdma/oob.h"
#include "mempool/slab.h"
#include "mempool/pool_registry.h"
#include "storage/tier_engine.h"
#include "qos/qos_sched.h"
#include "batch/batch_aggregator.h"
#include "replication/heartbeat.h"
#include "api/uds_server.h"
#include "api/metrics_agent.h"

#include <csignal>
#include <atomic>
#include <string>
#include <cstring>
#include <thread>
#include <chrono>
#include <fstream>
#include <filesystem>
#include <mutex>
#include <vector>
#include <algorithm>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>

static std::atomic<bool> g_stop{false};
static void on_sig(int) { g_stop.store(true); }

struct Args {
    std::string role       = "A";
    std::string self_ip;
    std::string peer_ip;
    std::string dev        = "mlx5_0";
    uint8_t     gid_idx    = 3;
    uint16_t    data_port  = 18515;      // OOB TCP port
    std::string uds_path   = "/tmp/native_rdma-dp.sock";
    std::string metrics_shm= "/tmp/native_rdma-metrics.shm";
    size_t      slab_bytes_1k = 1ULL * 1024 * 1024 * 1024;  // 1GB slab
    std::string snap_dir   = "/dev/shm/native_rdma_snap";
};

static void parse_args(int argc, char** argv, Args& a) {
    for (int i = 1; i < argc; ++i) {
        std::string s = argv[i];
        auto eq = s.find('=');
        std::string k = s.substr(0, eq);
        std::string v = (eq == std::string::npos) ? "" : s.substr(eq + 1);
        if      (k == "--role")        a.role = v;
        else if (k == "--self-ip")     a.self_ip = v;
        else if (k == "--peer-ip")     a.peer_ip = v;
        else if (k == "--dev")         a.dev = v;
        else if (k == "--gid-idx")     a.gid_idx = (uint8_t)std::stoi(v);
        else if (k == "--data-port")   a.data_port = (uint16_t)std::stoi(v);
        else if (k == "--uds")         a.uds_path = v;
        else if (k == "--metrics-shm")a.metrics_shm = v;
        else if (k == "--snap-dir")    a.snap_dir = v;
    }
}

// ---------- RPC payload helpers ----------
// RPC_KV_PUT body: [key]\0[val]
static bool parse_put_body(const std::string& body, std::string* k, std::string* v) {
    auto p = body.find('\0');
    if (p == std::string::npos) return false;
    *k = body.substr(0, p);
    *v = body.substr(p + 1);
    return true;
}

// ---------- QP role map ----------
// QP[0]: replication (RDMA WRITE primary -> backup)
// QP[1]: remote-read (RDMA READ)
// QP[7]: control/heartbeat (RDMA SEND/RECV)
static constexpr int QP_REPL = 0;
static constexpr int QP_READ = 1;
static constexpr int QP_HB   = 7;

int main(int argc, char** argv) {
    std::signal(SIGINT,  on_sig);
    std::signal(SIGTERM, on_sig);

    Args args; parse_args(argc, argv, args);
    NR_INFO("native_rdma_dp starting role=%s dev=%s gid_idx=%u self=%s peer=%s",
            args.role.c_str(), args.dev.c_str(), args.gid_idx,
            args.self_ip.c_str(), args.peer_ip.c_str());

    // 1) RDMA core
    nr::RdmaCore core;
    nr::RdmaConfig rcfg;
    rcfg.dev_name  = args.dev;
    rcfg.gid_index = args.gid_idx;
    rcfg.num_qp    = 8;
    if (!core.init(rcfg)) {
        NR_ERROR("RdmaCore init failed; exiting.");
        return 1;
    }

    // 2) Slab pool for 1KB objects
    nr::SlabPool slab;
    nr::SlabPool::Config scfg;
    scfg.slot_size   = 1024;
    scfg.total_bytes = args.slab_bytes_1k;
    scfg.use_hugepage= true;
    if (!slab.init(core, scfg)) {
        NR_WARN("slab init failed (HugePage not configured?); continue degraded.");
        return 1;
    }

    // 3) Register local pool
    nr::PoolInfo pi;
    pi.name      = "default/slab1k";
    pi.base_addr = (uint64_t)slab.base_addr();
    pi.length    = slab.capacity() * slab.slot_size();
    pi.rkey      = slab.rkey();
    pi.lkey      = slab.lkey();
    nr::PoolRegistry::instance().register_local(pi);

    // 4) QoS / Batch / Storage
    nr::QosSched qos;
    nr::QosSched::Config qcfg; qcfg.hi_qp_start = 0; qcfg.hi_qp_count = 2;
    qcfg.lo_qp_start = 2;     qcfg.lo_qp_count = 6;
    qos.init(core, qcfg);

    nr::BatchAggregator batch;
    nr::BatchAggregator::Config bcfg; bcfg.qp_idx = 4;
    batch.init(core, bcfg);

    nr::TierEngine tier;
    nr::TierEngine::Config tcfg;
    tier.init(tcfg);

    // 5) OOB handshake: role=B listens, role=A connects.
    const bool is_listener = (args.role == "B");
    nr::RemoteEndpoint peer;
    bool oob_ok = nr::oob_handshake(core,
        args.self_ip, args.peer_ip, args.data_port, is_listener,
        (uint64_t)slab.base_addr(),
        slab.capacity() * slab.slot_size(),
        slab.rkey(),
        &peer);
    if (!oob_ok) {
        NR_ERROR("OOB handshake failed; exiting.");
        return 2;
    }

    // 6) Pre-post HB/ctrl recv buffers and start heartbeat (real RDMA SEND).
    // Control messages on QP_HB have two kinds:
    //   tag=0x01 : HEARTBEAT  - payload: u64 ts_ms
    //   tag=0x02 : KV_INDEX   - payload: u16 key_len, u64 offset, u32 size, key[..]
    // Max control message fits in a 1KB slab slot easily.
    constexpr int    HB_RECV_CNT = 32;
    constexpr size_t HB_MSG_CAP  = 1024;
    constexpr uint8_t TAG_HB  = 0x01;
    constexpr uint8_t TAG_IDX = 0x02;
    std::vector<void*> hb_rx_buf(HB_RECV_CNT, nullptr);
    for (int i = 0; i < HB_RECV_CNT; ++i) {
        hb_rx_buf[i] = slab.alloc();
        if (!hb_rx_buf[i]) { NR_ERROR("slab oom for hb recv"); return 3; }
        core.post_recv(QP_HB, hb_rx_buf[i], HB_MSG_CAP, slab.lkey(),
                       /*wr_id=*/0xAA000000ULL | (uint64_t)i);
    }
    void* hb_tx_buf = slab.alloc();
    if (!hb_tx_buf) { NR_ERROR("slab oom for hb send"); return 3; }
    void* idx_tx_buf = slab.alloc();
    if (!idx_tx_buf) { NR_ERROR("slab oom for idx send"); return 3; }

    nr::Heartbeat hb;
    std::mutex hb_tx_mu, idx_tx_mu;
    hb.set_on_send([&]() {
        // [u8 tag][u8 pad=0][u16 pad=0][u64 ts_ms]
        uint8_t buf[16] = {0};
        buf[0] = TAG_HB;
        uint64_t ts = nr::now_ms();
        std::memcpy(buf + 8, &ts, 8);
        std::lock_guard<std::mutex> lk(hb_tx_mu);
        std::memcpy(hb_tx_buf, buf, sizeof(buf));
        (void)core.post_send(QP_HB, hb_tx_buf, sizeof(buf),
                             slab.lkey(), 0xBB00, /*signaled*/false);
    });
    hb.start(args.role == "A" ? "B" : "A", 1000, 3000);

    // Helper: send KV_INDEX update to peer (so backup can serve local GET).
    auto send_kv_index = [&](const std::string& k, uint64_t off, uint32_t sz) {
        // layout: [u8 tag][u8 pad][u16 klen][u64 off][u32 sz][key...]
        if (k.size() > HB_MSG_CAP - 16) return;
        std::lock_guard<std::mutex> lk(idx_tx_mu);
        uint8_t* p = (uint8_t*)idx_tx_buf;
        p[0] = TAG_IDX; p[1] = 0;
        uint16_t kl = (uint16_t)k.size();
        std::memcpy(p + 2, &kl, 2);
        std::memcpy(p + 4, &off, 8);
        std::memcpy(p + 12, &sz, 4);
        std::memcpy(p + 16, k.data(), kl);
        size_t total = 16 + kl;
        (void)core.post_send(QP_HB, idx_tx_buf, total,
                             slab.lkey(), 0xBB01, /*signaled*/false);
    };

    // ---- metric counters (declared before hb_thr so lambda can capture) ----
    std::atomic<uint64_t> ops_put{0}, ops_get{0};
    std::atomic<uint64_t> bytes_tx_1s{0}, bytes_rx_1s{0};
    std::atomic<uint64_t> last_repl_ns{0};

    // Latency ring: lock-free atomic counter + modulo indexing.
    // Keeps the most recent kLatRing samples; metrics thread snapshots to compute
    // avg/p99 every 200 ms.
    constexpr size_t kLatRing = 4096;
    std::vector<uint32_t> lat_ring(kLatRing, 0);  // nanoseconds
    std::atomic<uint64_t> lat_seq{0};
    auto lat_push = [&](uint64_t ns) {
        uint64_t idx = lat_seq.fetch_add(1, std::memory_order_relaxed);
        // Clamp to uint32_t range (sufficient: ~4.29s).
        lat_ring[idx % kLatRing] = (ns > 0xFFFFFFFFu) ? 0xFFFFFFFFu : (uint32_t)ns;
    };

    // RDMA busy window tracking: accumulate poll_cq busy nanoseconds in 1s window.
    std::atomic<uint64_t> busy_ns_1s{0};

    // 7) A dedicated thread drains QP_HB CQ: counts HB recv + repost.
    std::atomic<bool> hb_stop{false};
    std::thread hb_thr([&]() {
        while (!hb_stop.load(std::memory_order_relaxed)) {
            ibv_wc wcs[8];
            int n = core.poll_cq(QP_HB, wcs, 8);
            for (int i = 0; i < n; ++i) {
                auto& wc = wcs[i];
                if (wc.status != IBV_WC_SUCCESS) {
                    NR_WARN("hb qp WC err status=%d opcode=%d",
                            wc.status, wc.opcode);
                    continue;
                }
                if (wc.opcode == IBV_WC_RECV) {
                    int slot = (int)(wc.wr_id & 0xFFFF);
                    uint8_t* p = (uint8_t*)hb_rx_buf[slot];
                    uint8_t tag = p[0];
                    if (tag == TAG_HB) {
                        hb.tick("peer");
                    } else if (tag == TAG_IDX) {
                        uint16_t kl = 0; uint64_t off = 0; uint32_t sz = 0;
                        std::memcpy(&kl,  p + 2,  2);
                        std::memcpy(&off, p + 4,  8);
                        std::memcpy(&sz,  p + 12, 4);
                        std::string k((char*)(p + 16), kl);
                        tier.put_meta(k, off, sz);
                        bytes_rx_1s.fetch_add(sz);
                    }
                    // Repost.
                    core.post_recv(QP_HB, hb_rx_buf[slot], HB_MSG_CAP,
                                   slab.lkey(), wc.wr_id);
                }
                // IBV_WC_SEND: nothing to do.
            }
            if (n == 0) std::this_thread::sleep_for(std::chrono::microseconds(500));
        }
    });

    // 8) Metrics agent
    nr::MetricsAgent ma;
    ma.attach(args.metrics_shm.c_str());

    std::thread metrics_thr([&]() {
        uint64_t last = nr::now_ms();
        // Scratch buffer for snapshot + partial sort (nth_element for p99).
        std::vector<uint32_t> snap;
        snap.reserve(kLatRing);
        while (!g_stop.load(std::memory_order_relaxed)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            if (!ma.data()) continue;
            auto* m = ma.data();
            m->obj_dram.store(tier.count(nr::Tier::DRAM));
            m->obj_nvme.store(tier.count(nr::Tier::NVME));
            m->obj_hdd.store(tier.count(nr::Tier::HDD));
            uint64_t total = ops_put.load() + ops_get.load();
            m->ops_total.store(total);
            m->ops_hi.store(ops_put.load());
            m->ops_lo.store(ops_get.load());
            uint64_t now = nr::now_ms();
            double secs = (now - last) / 1000.0; if (secs <= 0) secs = 0.001;
            uint64_t tx = bytes_tx_1s.exchange(0);
            uint64_t rx = bytes_rx_1s.exchange(0);
            m->bw_tx_gbps.store(tx * 8.0 / 1e9 / secs);
            m->bw_rx_gbps.store(rx * 8.0 / 1e9 / secs);

            // Snapshot the ring (copy current valid samples).
            uint64_t seq = lat_seq.load(std::memory_order_relaxed);
            size_t valid = (seq >= kLatRing) ? kLatRing : (size_t)seq;
            snap.assign(lat_ring.begin(), lat_ring.begin() + valid);
            if (!snap.empty()) {
                // Strip zeros (uninitialized slots if any) to avoid pulling avg down.
                uint64_t sum = 0; size_t cnt = 0;
                for (auto v : snap) { if (v) { sum += v; ++cnt; } }
                double avg_us = cnt ? (double)sum / cnt / 1000.0 : 0.0;
                m->lat_avg_us.store(avg_us);
                if (cnt >= 20) {
                    // Non-zero subset for p99
                    std::vector<uint32_t> nz; nz.reserve(cnt);
                    for (auto v : snap) if (v) nz.push_back(v);
                    size_t p99_idx = (size_t)(nz.size() * 0.99);
                    if (p99_idx >= nz.size()) p99_idx = nz.size() - 1;
                    std::nth_element(nz.begin(), nz.begin() + p99_idx, nz.end());
                    m->lat_p99_us.store((double)nz[p99_idx] / 1000.0);
                }
            } else {
                m->lat_avg_us.store(0.0);
                m->lat_p99_us.store(0.0);
            }

            double lag_us = last_repl_ns.load() / 1000.0;
            m->replica_lag_us.store(lag_us);

            // RDMA utilization: fraction of wall time spent in completed replication.
            // last_repl_ns is the most recent single-op time; for throughput we derive
            // from ops_put delta in this window.
            uint64_t busy = busy_ns_1s.exchange(0);
            double util = (secs > 0) ? (double)busy / (secs * 1e9) * 100.0 : 0.0;
            if (util > 100.0) util = 100.0;
            m->rdma_util_pct.store(util);

            m->ts_ns.store(nr::now_ns());
            last = now;
            tier.tick_migration();
        }
    });

    // 9) UDS RPC handlers
    auto do_put = [&](const std::string& body, std::string* resp) {
        std::string k, v;
        if (!parse_put_body(body, &k, &v)) {
            *resp = "{\"ok\":false,\"err\":\"bad put body\"}"; return;
        }
        if (v.size() > slab.slot_size()) {
            *resp = "{\"ok\":false,\"err\":\"value too large\"}"; return;
        }
        void* slot = slab.alloc();
        if (!slot) {
            *resp = "{\"ok\":false,\"err\":\"slab oom\"}"; return;
        }
        std::memcpy(slot, v.data(), v.size());
        uint64_t off = (uint64_t)((char*)slot - (char*)slab.base_addr());

        tier.put_meta(k, off, (uint32_t)v.size());

        // Replicate to peer at the SAME offset so primary & backup indices align.
        uint64_t remote_addr = peer.slab_base + off;
        uint64_t t0 = nr::now_ns();
        int rc = core.post_write(QP_REPL, slot, v.size(), slab.lkey(),
                                 remote_addr, peer.slab_rkey,
                                 /*imm*/0, /*wr_id*/0xC0000000 | (off & 0xFFFFFFF),
                                 /*signaled*/true);
        bool repl_ok = (rc == 0);
        if (repl_ok) {
            ibv_wc wc;
            while (true) {
                int n = core.poll_cq(QP_REPL, &wc, 1);
                if (n < 0) { repl_ok = false; break; }
                if (n == 0) continue;
                repl_ok = (wc.status == IBV_WC_SUCCESS);
                break;
            }
        }
        uint64_t dt = nr::now_ns() - t0;
        last_repl_ns.store(dt);
        lat_push(dt);
        busy_ns_1s.fetch_add(dt);
        if (repl_ok) {
            // Push index to peer so backup can serve local GET.
            send_kv_index(k, off, (uint32_t)v.size());
            bytes_tx_1s.fetch_add(v.size());
            ops_put.fetch_add(1);
            char buf[192];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":true,\"key\":\"%s\",\"size\":%zu,"
                "\"offset\":%lu,\"repl_ns\":%lu}",
                k.c_str(), v.size(), (unsigned long)off, (unsigned long)dt);
            resp->assign(buf, n);
        } else {
            *resp = "{\"ok\":false,\"err\":\"replicate failed\"}";
        }
    };

    auto do_get = [&](const std::string& body, std::string* resp) {
        std::string k = body;
        uint64_t off = 0; uint32_t sz = 0;
        if (tier.get_meta(k, &off, &sz)) {
            // Local hit
            std::string val(sz, '\0');
            std::memcpy(&val[0], (char*)slab.base_addr() + off, sz);
            ops_get.fetch_add(1);
            bytes_rx_1s.fetch_add(sz);
            // Only print the first 64 bytes to keep the JSON small.
            std::string preview = val.substr(0, std::min<size_t>(64, val.size()));
            char hdr[96];
            int n = std::snprintf(hdr, sizeof(hdr),
                "{\"ok\":true,\"hit\":\"local\",\"size\":%u,\"val\":\"",
                sz);
            resp->assign(hdr, n);
            for (char c : preview) {
                if (c == '"' || c == '\\') { resp->push_back('\\'); resp->push_back(c); }
                else if ((unsigned char)c < 0x20) { resp->push_back('?'); }
                else resp->push_back(c);
            }
            resp->append("\"}");
            return;
        }
        // Miss on both sides (index is propagated via KV_INDEX control msg,
        // so backup would already have metadata on successful replication).
        *resp = "{\"ok\":false,\"err\":\"not found\"}";
    };

    auto do_snapshot = [&](const std::string& body, std::string* resp) {
        std::string tag = body.empty() ? "snap" : body;
        std::error_code ec;
        std::filesystem::create_directories(args.snap_dir, ec);
        std::string idx_path = args.snap_dir + "/snap_" + tag + ".idx";
        std::string dat_path = args.snap_dir + "/snap_" + tag + ".dat";
        std::ofstream idx(idx_path, std::ios::binary|std::ios::trunc);
        std::ofstream dat(dat_path, std::ios::binary|std::ios::trunc);
        if (!idx || !dat) {
            *resp = "{\"ok\":false,\"err\":\"open snap files failed\"}"; return;
        }
        uint64_t nobj = 0, nbytes = 0;
        tier.for_each([&](const std::string& key, const nr::ObjectMeta& m) -> bool {
            uint32_t kl = (uint32_t)key.size();
            idx.write((const char*)&kl, 4);
            idx.write(key.data(), kl);
            idx.write((const char*)&m.offset, 8);
            idx.write((const char*)&m.size, 4);
            dat.write((const char*)slab.base_addr() + m.offset, m.size);
            nobj++; nbytes += m.size;
            return true;
        });
        idx.close(); dat.close();
        char buf[256];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"tag\":\"%s\",\"objects\":%lu,\"bytes\":%lu,"
            "\"idx\":\"%s\",\"dat\":\"%s\"}",
            tag.c_str(), (unsigned long)nobj, (unsigned long)nbytes,
            idx_path.c_str(), dat_path.c_str());
        resp->assign(buf, n);
    };

    nr::UdsServer uds;
    uds.set_handler([&](const std::string& kind, const std::string& body,
                        std::string* resp) {
        if      (kind == "RPC_CLUSTER_STATUS") {
            char buf[256];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":true,\"self\":\"%s\",\"peer_alive\":%s,"
                "\"peer_slab_base\":%lu,\"peer_slab_rkey\":%u,\"peer_num_qp\":%u}",
                args.role.c_str(),
                hb.peer_alive() ? "true" : "false",
                (unsigned long)peer.slab_base,
                peer.slab_rkey,
                (unsigned)peer.qpns.size());
            resp->assign(buf, n);
        }
        else if (kind == "RPC_KV_PUT")   do_put(body, resp);
        else if (kind == "RPC_KV_GET")   do_get(body, resp);
        else if (kind == "RPC_SNAPSHOT") do_snapshot(body, resp);
        else {
            *resp = "{\"ok\":false,\"err\":\"unknown rpc kind\"}";
        }
    });
    uds.start(args.uds_path);

    NR_INFO("native_rdma_dp ready. Ctrl-C to exit.");
    while (!g_stop.load(std::memory_order_relaxed)) {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }

    NR_INFO("native_rdma_dp shutting down...");
    uds.stop();
    hb.stop();
    hb_stop.store(true);
    if (hb_thr.joinable()) hb_thr.join();
    if (metrics_thr.joinable()) metrics_thr.join();
    batch.shutdown();
    slab.shutdown();
    return 0;
}
