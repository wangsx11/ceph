// native_rdma data-plane entry point.
// W2: full OOB handshake + real RDMA WRITE/READ + RDMA SEND heartbeat + real KV.

#include "common/logger.h"
#include "common/time_util.h"
#include "rdma/rdma_core.h"
#include "rdma/oob.h"
#include "mempool/slab.h"
#include "mempool/pool_registry.h"
#include "storage/tier_engine.h"
#include "storage/io_scheduler.h"
#include "storage/prefetcher.h"
#include "storage/compress.h"
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
    size_t      slab_slot_size = 1024;                      // W4 bw: configurable slot size
    std::string snap_dir   = "/dev/shm/native_rdma_snap";
    // W4: multi-tier storage backing paths.
    std::string nvme_path  = "/dev/shm/native_rdma_warm";
    std::string hdd_path   = "/dev/shm/native_rdma_cold";
    uint64_t    dram_demote_idle_ms = 10000;  // -> NVMe after 10s idle
    uint64_t    nvme_demote_idle_ms = 30000;  // -> HDD  after 30s idle
    int         migrate_interval_ms = 1000;
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
        else if (k == "--slab-slot-size") a.slab_slot_size = std::stoull(v);
        else if (k == "--slab-total-bytes") a.slab_bytes_1k = std::stoull(v);
        else if (k == "--nvme-path")  a.nvme_path = v;
        else if (k == "--hdd-path")   a.hdd_path = v;
        else if (k == "--dram-demote-idle-ms") a.dram_demote_idle_ms = std::stoull(v);
        else if (k == "--nvme-demote-idle-ms") a.nvme_demote_idle_ms = std::stoull(v);
        else if (k == "--migrate-interval-ms") a.migrate_interval_ms = std::stoi(v);
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

    // 2) Slab pool (configurable slot size for bandwidth tests)
    nr::SlabPool slab;
    nr::SlabPool::Config scfg;
    scfg.slot_size   = args.slab_slot_size;
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
    tcfg.nvme_path = args.nvme_path;
    tcfg.hdd_path  = args.hdd_path;
    tcfg.migrate_interval_ms  = args.migrate_interval_ms;
    tcfg.dram_demote_idle_ns  = args.dram_demote_idle_ms * 1000000ULL;
    tcfg.nvme_demote_idle_ns  = args.nvme_demote_idle_ms * 1000000ULL;
    tier.init(tcfg);

    // Prefetcher (W4 M1-3): stride + Markov-1 prediction over GET accesses.
    nr::Prefetcher prefetcher;
    prefetcher.init();

    // IoScheduler: FG (NVMe warm) + BG (HDD cold), both via io_uring.
    // Backing directories must exist; create if missing.
    {
        std::error_code ec;
        std::filesystem::create_directories(
            std::filesystem::path(args.nvme_path).parent_path(), ec);
        std::filesystem::create_directories(
            std::filesystem::path(args.hdd_path ).parent_path(), ec);
    }
    nr::IoScheduler io;
    nr::IoScheduler::Config iocfg;
    iocfg.fg_path = args.nvme_path;
    iocfg.bg_path = args.hdd_path;
    iocfg.sq_depth = 1024;
    iocfg.sq_poll_fg = false;
    io.init(iocfg);
    tier.set_io_scheduler(&io);

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

    // 8b) Tier migrator thread (W4): demote cold DRAM/NVMe objects.
    //
    // Every `migrate_interval_ms` we scan the index and move objects whose
    // `last_access` exceeded the configured idle window. DRAM slots are
    // returned to the slab allocator after successful demotion.
    std::atomic<bool> mig_stop{false};
    std::atomic<uint64_t> mig_d_n_{0}, mig_n_h_{0};  // counters for stats RPC
    std::thread mig_thr([&]() {
        while (!mig_stop.load(std::memory_order_relaxed) &&
               !g_stop.load(std::memory_order_relaxed)) {
            std::this_thread::sleep_for(
                std::chrono::milliseconds(args.migrate_interval_ms));
            uint64_t now_n = nr::now_ns();
            const uint64_t dram_idle = args.dram_demote_idle_ms * 1000000ULL;
            const uint64_t nvme_idle = args.nvme_demote_idle_ms * 1000000ULL;

            // Collect demotion candidates (copy key+tier) under lock, then
            // call demote() without holding the index lock.
            struct Cand { std::string key; nr::Tier from; nr::Tier to;
                          uint64_t dram_off; };
            std::vector<Cand> cands;
            cands.reserve(128);
            tier.for_each([&](const std::string& k, const nr::ObjectMeta& m) {
                if (cands.size() >= 128) return false;
                if (m.tier == nr::Tier::DRAM && dram_idle > 0 &&
                    m.last_access > 0 && now_n - m.last_access > dram_idle) {
                    cands.push_back({k, nr::Tier::DRAM, nr::Tier::NVME, m.offset});
                } else if (m.tier == nr::Tier::NVME && nvme_idle > 0 &&
                           m.last_access > 0 && now_n - m.last_access > nvme_idle) {
                    cands.push_back({k, nr::Tier::NVME, nr::Tier::HDD, 0});
                }
                return true;
            });
            for (auto& c : cands) {
                bool ok = tier.demote(c.key, c.to, slab.base_addr(),
                                      slab.capacity() * slab.slot_size());
                if (!ok) continue;
                if (c.from == nr::Tier::DRAM) {
                    // Return the DRAM slot to the slab allocator.
                    void* p = (char*)slab.base_addr() + c.dram_off;
                    slab.free(p);
                    mig_d_n_.fetch_add(1);
                } else {
                    mig_n_h_.fetch_add(1);
                }
            }
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
        // Reuse existing slot if key already exists (avoid slot leak on updates).
        uint64_t off = 0; uint32_t old_sz = 0;
        void* slot = nullptr;
        if (tier.get_meta(k, &off, &old_sz)) {
            // In-place overwrite; slot_size is fixed, any new size <= slot_size fits.
            slot = (char*)slab.base_addr() + off;
        } else {
            slot = slab.alloc();
            if (!slot) {
                *resp = "{\"ok\":false,\"err\":\"slab oom\"}"; return;
            }
            off = (uint64_t)((char*)slot - (char*)slab.base_addr());
        }
        std::memcpy(slot, v.data(), v.size());

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
        nr::ObjectMeta meta{};
        if (!tier.get_meta_full(k, &meta)) {
            *resp = "{\"ok\":false,\"err\":\"not found\"}";
            return;
        }
        // Feed access history to prefetcher (before any promote).
        prefetcher.on_access(k);
        uint32_t sz = meta.size;
        const char* hit_kind = "local";
        // Cold hit: object lives on NVMe/HDD, promote it back to DRAM first.
        if (meta.tier != nr::Tier::DRAM) {
            void* slot = slab.alloc();
            if (!slot) {
                *resp = "{\"ok\":false,\"err\":\"slab oom on promote\"}";
                return;
            }
            uint64_t dram_off = (uint64_t)((char*)slot - (char*)slab.base_addr());
            if (!tier.promote(k, slot, dram_off)) {
                slab.free(slot);
                *resp = "{\"ok\":false,\"err\":\"promote failed\"}";
                return;
            }
            hit_kind = (meta.tier == nr::Tier::NVME) ? "nvme_promote" : "hdd_promote";
            // Read back from slab at the new offset (sz/val populated below).
            meta.offset = dram_off;
        }
        // Read from DRAM slab.
        std::string val(sz, '\0');
        std::memcpy(&val[0], (char*)slab.base_addr() + meta.offset, sz);
        ops_get.fetch_add(1);
        bytes_rx_1s.fetch_add(sz);
        std::string preview = val.substr(0, std::min<size_t>(64, val.size()));
        char hdr[128];
        int n = std::snprintf(hdr, sizeof(hdr),
            "{\"ok\":true,\"hit\":\"%s\",\"size\":%u,\"val\":\"",
            hit_kind, sz);
        resp->assign(hdr, n);
        for (char c : preview) {
            if (c == '"' || c == '\\') { resp->push_back('\\'); resp->push_back(c); }
            else if ((unsigned char)c < 0x20) { resp->push_back('?'); }
            else resp->push_back(c);
        }
        resp->append("\"}");
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
        std::vector<char> scratch;
        tier.for_each([&](const std::string& key, const nr::ObjectMeta& m) -> bool {
            uint32_t kl = (uint32_t)key.size();
            idx.write((const char*)&kl, 4);
            idx.write(key.data(), kl);
            idx.write((const char*)&m.offset, 8);
            idx.write((const char*)&m.size, 4);
            // Read object bytes from whichever tier owns it.
            if (m.tier == nr::Tier::DRAM) {
                dat.write((const char*)slab.base_addr() + m.offset, m.size);
            } else if (m.tier == nr::Tier::NVME) {
                scratch.assign(m.size, 0);
                int r = io.sync_read(nr::IoScheduler::Prio::FG, scratch.data(),
                                     m.size, m.offset);
                if (r == (int)m.size) dat.write(scratch.data(), m.size);
                else dat.write(std::string(m.size, '\0').data(), m.size);
            } else {
                // HDD: read compressed_size bytes, decompress if needed.
                uint32_t on_disk = m.compressed_size ? m.compressed_size : m.size;
                std::string enc(on_disk, '\0');
                int r = io.sync_read(nr::IoScheduler::Prio::BG, enc.data(),
                                     on_disk, m.offset);
                if (r != (int)on_disk) {
                    dat.write(std::string(m.size, '\0').data(), m.size);
                } else if (m.algo != 0) {
                    std::string dec;
                    auto algo = (m.algo == 1) ? nr::CompressAlgo::ZSTD
                                              : nr::CompressAlgo::LZ4;
                    if (nr::CompressEngine::decompress(algo, enc, &dec)
                        && dec.size() == m.size) {
                        dat.write(dec.data(), dec.size());
                    } else {
                        dat.write(std::string(m.size, '\0').data(), m.size);
                    }
                } else {
                    dat.write(enc.data(), m.size);
                }
            }
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

    auto do_tier_stats = [&](std::string* resp) {
        auto evs = tier.recent_events();
        std::string out = "{\"ok\":true,";
        char hdr[256];
        int n = std::snprintf(hdr, sizeof(hdr),
            "\"dram\":%lu,\"nvme\":%lu,\"hdd\":%lu,"
            "\"demoted_d_n\":%lu,\"demoted_n_h\":%lu,\"events\":[",
            (unsigned long)tier.count(nr::Tier::DRAM),
            (unsigned long)tier.count(nr::Tier::NVME),
            (unsigned long)tier.count(nr::Tier::HDD),
            (unsigned long)mig_d_n_.load(),
            (unsigned long)mig_n_h_.load());
        out.append(hdr, n);
        bool first = true;
        // Show latest first, cap to 16 entries to keep payload small.
        size_t show = std::min<size_t>(16, evs.size());
        for (size_t i = evs.size(); i > 0 && (evs.size() - i) < show; --i) {
            const auto& e = evs[i - 1];
            auto tier_str = [](nr::Tier t){
                return t==nr::Tier::DRAM?"dram":t==nr::Tier::NVME?"nvme":"hdd";
            };
            if (!first) out.push_back(',');
            first = false;
            char b[256];
            int k = std::snprintf(b, sizeof(b),
                "{\"ts_ns\":%lu,\"key\":\"%s\",\"from\":\"%s\",\"to\":\"%s\","
                "\"bytes\":%lu}",
                (unsigned long)e.ts_ns,
                e.key.c_str(), tier_str(e.from), tier_str(e.to),
                (unsigned long)e.bytes);
            out.append(b, k);
        }
        out.append("]}");
        *resp = std::move(out);
    };

    auto do_tier_demote = [&](const std::string& body, std::string* resp) {
        // body layout: "<key>\0<tier>" where tier is "nvme" or "hdd".
        auto p = body.find('\0');
        std::string k, tier_str;
        if (p == std::string::npos) { k = body; tier_str = "nvme"; }
        else { k = body.substr(0, p); tier_str = body.substr(p + 1); }
        nr::Tier to = (tier_str == "hdd") ? nr::Tier::HDD : nr::Tier::NVME;

        nr::ObjectMeta before{};
        if (!tier.get_meta_full(k, &before)) {
            *resp = "{\"ok\":false,\"err\":\"key not found\"}"; return;
        }
        bool ok = tier.demote(k, to, slab.base_addr(),
                              slab.capacity() * slab.slot_size());
        if (ok && before.tier == nr::Tier::DRAM) {
            slab.free((char*)slab.base_addr() + before.offset);
            mig_d_n_.fetch_add(1);
        } else if (ok && before.tier == nr::Tier::NVME) {
            mig_n_h_.fetch_add(1);
        }
        char buf[128];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":%s,\"key\":\"%s\",\"to\":\"%s\"}",
            ok ? "true" : "false", k.c_str(), tier_str.c_str());
        resp->assign(buf, n);
    };

    auto do_prefetch_stats = [&](const std::string& body, std::string* resp) {
        auto st = prefetcher.stats();
        auto preds = prefetcher.predict(body);
        std::string out;
        char hdr[200];
        int n = std::snprintf(hdr, sizeof(hdr),
            "{\"ok\":true,\"total\":%lu,\"hits_stride\":%lu,\"hits_markov\":%lu,"
            "\"query\":\"%s\",\"predicted\":[",
            (unsigned long)st.total_access,
            (unsigned long)st.hits_stride,
            (unsigned long)st.hits_markov,
            body.c_str());
        out.assign(hdr, n);
        bool first = true;
        for (auto& p : preds) {
            if (p.size() > 120) continue;
            if (!first) out.push_back(',');
            first = false;
            out.push_back('"');
            for (char c : p) {
                if (c == '"' || c == '\\') { out.push_back('\\'); out.push_back(c); }
                else if ((unsigned char)c < 0x20) out.push_back('?');
                else out.push_back(c);
            }
            out.push_back('"');
        }
        out.append("]}");
        *resp = std::move(out);
    };

    auto do_compress_stats = [&](std::string* resp) {
        auto s = tier.compress_stats();
        double ratio = (s.raw_bytes > 0)
            ? (double)s.cmp_bytes / (double)s.raw_bytes : 0.0;
        char buf[256];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"raw_bytes\":%lu,\"cmp_bytes\":%lu,"
            "\"objects\":%lu,\"ratio\":%.4f,\"saved_bytes\":%ld}",
            (unsigned long)s.raw_bytes, (unsigned long)s.cmp_bytes,
            (unsigned long)s.n_compressed, ratio,
            (long)((long long)s.raw_bytes - (long long)s.cmp_bytes));
        resp->assign(buf, n);
    };

    // Admin: wipe the in-memory KV index, free all DRAM slab slots, reset
    // counters (ops/tier/migration/compression). Lets the operator recover
    // from bench-test residue (e.g. 300k bk_* keys occupying the slab) without
    // having to restart the data plane.
    auto do_admin_flush = [&](std::string* resp) {
        auto dram_offs = tier.reset_all();
        for (uint64_t off : dram_offs) {
            slab.free((char*)slab.base_addr() + off);
        }
        // Reset process-level counters so the UI starts fresh.
        ops_put.store(0);
        ops_get.store(0);
        bytes_tx_1s.store(0);
        bytes_rx_1s.store(0);
        busy_ns_1s.store(0);
        last_repl_ns.store(0);
        mig_d_n_.store(0);
        mig_n_h_.store(0);
        char buf[128];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"freed_slabs\":%zu}", dram_offs.size());
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
        else if (kind == "RPC_TIER_STATS")  do_tier_stats(resp);
        else if (kind == "RPC_TIER_DEMOTE") do_tier_demote(body, resp);
        else if (kind == "RPC_PREFETCH_STATS") do_prefetch_stats(body, resp);
        else if (kind == "RPC_COMPRESS_STATS") do_compress_stats(resp);
        else if (kind == "RPC_ADMIN_FLUSH")    do_admin_flush(resp);
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
    mig_stop.store(true);
    if (hb_thr.joinable()) hb_thr.join();
    if (metrics_thr.joinable()) metrics_thr.join();
    if (mig_thr.joinable())     mig_thr.join();
    batch.shutdown();
    io.shutdown();
    slab.shutdown();
    return 0;
}
