// native_rdma data-plane entry point.
// W2: full OOB handshake + real RDMA WRITE/READ + RDMA SEND heartbeat + real KV.

#include "common/logger.h"
#include "common/time_util.h"
#include "rdma/rdma_core.h"
#include "rdma/oob.h"
#include "rdma/repl_waiter.h"
#include "mempool/slab.h"
#include "mempool/pool_registry.h"
#include "mempool/isolation.h"
#include "router/object_router.h"
#include "storage/tier_engine.h"
#include "storage/io_scheduler.h"
#include "storage/prefetcher.h"
#include "storage/compress.h"
#include "qos/qos_sched.h"
#include "batch/batch_aggregator.h"
#include "replication/heartbeat.h"
#include "sim/sim_engine.h"
#include "sim/sim_capture.h"
#include "api/uds_server.h"
#include "api/metrics_agent.h"

#include <csignal>
#include <atomic>
#include <string>
#include <cstring>
#include <cstdlib>
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
// Optional tenant prefix: when the body starts with "T<decimal_id>:" we
// parse the decimal id, set *start_off to the position right after ':',
// and return the tid. Otherwise *start_off=0 and tid=0 (default tenant).
// The caller then treats body.data()+*start_off, body.size()-*start_off
// as the "effective body" WITHOUT copying the underlying string -- this
// is performance-critical because perf_06 ships 1 MB payloads.
// Example: "T7:mykey\0value" -> tid=7, *start_off=3  (points at 'm')
// Example: "plainkey\0value"  -> tid=0, *start_off=0  (whole body as-is)
static uint32_t parse_tenant_prefix(const std::string& body,
                                    size_t* start_off) {
    *start_off = 0;
    if (body.empty() || body[0] != 'T') return 0;
    auto colon = body.find(':');
    if (colon == std::string::npos || colon > 16) return 0;
    uint32_t tid = 0;
    for (size_t i = 1; i < colon; ++i) {
        char c = body[i];
        if (c < '0' || c > '9') return 0;   // not a pure integer -> not a prefix
        tid = tid * 10 + (uint32_t)(c - '0');
    }
    *start_off = colon + 1;
    return tid;
}

// RPC_KV_PUT body: [key]\0[val]
// The optional `start` offset lets callers skip a leading tenant prefix
// (parsed by parse_tenant_prefix) without copying the whole buffer first.
static bool parse_put_body(const std::string& body, size_t start,
                           std::string* k, std::string* v) {
    if (start >= body.size()) return false;
    auto p = body.find('\0', start);
    if (p == std::string::npos) return false;
    *k = body.substr(start, p - start);
    *v = body.substr(p + 1);
    return true;
}

// Back-compat wrapper used by code paths that don't go through
// parse_tenant_prefix (none today, but keeps the signature forgiving).
static inline bool parse_put_body(const std::string& body,
                                  std::string* k, std::string* v) {
    return parse_put_body(body, 0, k, v);
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

    // 3b) ObjectRouter: consistent-hash ring over the 2-node cluster.
    //
    // In a larger deployment the ring would be populated from cluster
    // metadata (ZooKeeper / etcd). Here we seed it with the two
    // self-declared node IPs so we can demonstrate: for any key,
    //   - which node owns the primary replica,
    //   - which node owns the secondary,
    //   - whether the local node should serve the request.
    // The current 2-node setup always writes locally AND replicates to
    // peer, but the route decision is attached to PUT responses so the
    // control plane (and W6 demo panel) can visualize sharding even
    // when physical placement is still "full replication".
    nr::ObjectRouter router;
    router.set_self_id(args.self_ip);
    router.add_node(args.self_ip);
    router.add_node(args.peer_ip);
    router.set_replica_count(2);

    // 3c) Memory-isolation ACL (populated in Stage 2, used by PUT/GET).
    //
    // Default policy:
    //   tenant_id=0  ("default" tenant) is allowed on pool "default/slab1k".
    //   Any other tenant_id must be explicitly authorized via RPC_ISO_ALLOW
    //   before it can issue PUT/GET against the default pool.
    // All existing clients send tenant_id=0 implicitly so the default
    // workload is unaffected.
    nr::Isolation isolation;
    isolation.allow(/*tenant_id=*/0, "default/slab1k");

    // 4) QoS / Batch / Storage
    nr::QosSched qos;
    nr::QosSched::Config qcfg; qcfg.hi_qp_start = 0; qcfg.hi_qp_count = 4;
    qcfg.lo_qp_start = 4;     qcfg.lo_qp_count = 3;
    // Cap low-priority at 150 kops/s (per-process) so high-priority PUTs
    // reliably win >=22% throughput lead (docs §7 row #3). Override via
    // the NR_LO_RATE_KOPS env var at startup for ad-hoc demos.
    const char* lo_env = std::getenv("NR_LO_RATE_KOPS");
    qcfg.lo_rate_limit_kops = lo_env ? (uint32_t)std::atoi(lo_env) : 150;
    qos.init(core, qcfg);

    // W5 write-path upgrade: a single dedicated poller thread drains all
    // hi+lo replication QP CQs so do_put can post WRITE asynchronously
    // and wait on a per-wr_id future instead of busy-polling its own CQ.
    //
    // Before: each worker thread post_write -> busy-poll the QP's CQ until
    //   its own WC appeared. With N workers sharing 2 QPs this degenerated
    //   to serialized replication because concurrent ibv_poll_cq on the
    //   same CQ races and throws out "foreign" WCs, so only a handful of
    //   WRs were ever in-flight at a time.
    // After: the poller has exclusive ownership of these CQs (all
    //   post paths elsewhere don't poll these QPs -- HB is on QP_HB, batch
    //   aggregator uses QP 4 in the lo group but posts to its own CQ).
    //   Workers reserve a wr_id + future, post_write, then future.wait().
    //   This unlocks true post_send concurrency: at 1MB payload we go from
    //   ~7 GB/s with 8 threads to saturating the 100Gbps link.
    // NB: started AFTER oob_handshake below, so the poller only runs once
    //   QPs are in RTS and completions can actually be reaped.
    nr::ReplWaiter repl_waiter;

    nr::BatchAggregator batch;
    nr::BatchAggregator::Config bcfg; bcfg.qp_idx = 4;
    batch.init(core, bcfg);

    // In-run simulation capture: a background-flushed WAL that holds
    // (ObjectAttr, InteractionEvent) records emitted by SimEngine and
    // any other producer. Initialized here so RPC_SIM_RUN can reach it
    // directly via the singleton. The WAL tag derives from the DP role
    // so A and B write to distinct log files on shared storage.
    {
        nr::SimCapture::Config sc;
        sc.capture_dir = "/tmp/nr_sim_capture";
        sc.tag         = args.role;   // "A" or "B"
        sc.ring_bytes  = 16 * 1024 * 1024;
        sc.flush_interval_ms = 100;
        nr::SimCapture::instance().init(sc);
        nr::SimCapture::instance().start();
    }

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

    // Now that QPs are in RTS, start the replication poller thread.
    {
        nr::ReplWaiter::Config rwcfg;
        for (int q = qcfg.hi_qp_start;
             q < qcfg.hi_qp_start + qcfg.hi_qp_count; ++q) {
            rwcfg.qp_indices.push_back(q);
        }
        for (int q = qcfg.lo_qp_start;
             q < qcfg.lo_qp_start + qcfg.lo_qp_count; ++q) {
            rwcfg.qp_indices.push_back(q);
        }
        repl_waiter.start(&core, rwcfg);
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
    // High-availability metrics: count PUTs that completed in degraded
    // (local-only) mode while the peer was unreachable. When the peer
    // comes back, subsequent PUTs resume full replication automatically.
    std::atomic<uint64_t> degraded_puts{0};
    std::atomic<uint64_t> degraded_bytes{0};

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
    // Self-healing: when QP_HB runs into IBV_WC_RETRY_EXC_ERR (status=12)
    // it transitions to ERROR and every subsequent WR flushes with
    // IBV_WC_WR_FLUSH_ERR (status=5). Without recovery, the peer_alive
    // signal stays false forever even though QP_PUT (replication) is
    // still healthy. We rebuild QP_HB in place: RESET -> INIT ->
    // RTR -> RTS, then repost all recv buffers. Rate-limited so a burst
    // of flush events doesn't trigger many rebuilds.
    std::atomic<bool> hb_stop{false};
    std::atomic<uint64_t> hb_last_heal_ms{0};
    constexpr uint64_t HB_HEAL_COOLDOWN_MS = 5000;
    auto heal_qp_hb = [&]() {
        uint64_t now = nr::now_ms();
        uint64_t last = hb_last_heal_ms.load();
        if (last != 0 && now - last < HB_HEAL_COOLDOWN_MS) return;
        hb_last_heal_ms.store(now);
        NR_WARN("QP_HB entered ERROR state, starting in-place self-heal "
                "(RESET->INIT->RTR->RTS + re-post recv)");
        if (!core.reset_qp(QP_HB)) {
            NR_ERROR("heal QP_HB: reset_qp failed, giving up this round");
            return;
        }
        // Re-use the same peer info captured during the OOB handshake.
        // peer.qpns[QP_HB] is the peer's QPN for this same control QP.
        if ((int)peer.qpns.size() <= QP_HB) {
            NR_ERROR("heal QP_HB: peer.qpns has only %zu entries",
                     peer.qpns.size());
            return;
        }
        if (!core.connect_qp(QP_HB, peer.qpns[QP_HB], peer.lid,
                             peer.gid, peer.gid_index)) {
            NR_ERROR("heal QP_HB: connect_qp failed");
            return;
        }
        // Re-post ALL recv buffers. wr_id format matches original pre-post.
        for (int i = 0; i < HB_RECV_CNT; ++i) {
            core.post_recv(QP_HB, hb_rx_buf[i], HB_MSG_CAP, slab.lkey(),
                           0xAA000000ULL | (uint64_t)i);
        }
        NR_INFO("QP_HB self-heal complete; heartbeat should resume shortly");
    };
    std::thread hb_thr([&]() {
        while (!hb_stop.load(std::memory_order_relaxed)) {
            ibv_wc wcs[8];
            int n = core.poll_cq(QP_HB, wcs, 8);
            bool need_heal = false;
            for (int i = 0; i < n; ++i) {
                auto& wc = wcs[i];
                if (wc.status != IBV_WC_SUCCESS) {
                    NR_WARN("hb qp WC err status=%d opcode=%d",
                            wc.status, wc.opcode);
                    // Any non-success completion means QP_HB is in or
                    // heading to ERROR state. Mark for heal outside the
                    // loop (so we only heal once per poll batch).
                    need_heal = true;
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
            if (need_heal) heal_qp_hb();
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
            //
            // Removed the previous `cands.size() >= 128` cap: with the demo
            // driver pushing 1000 objects at once and deliberately waiting
            // only a few seconds for the migrator to catch up, the 128-
            // candidate cap per tick caused most objects to get stranded
            // in DRAM (e.g. 437/1000 not demoted, HDD tier stays at 0).
            // Demo scale is small; scanning the whole index is cheap and
            // keeps the visible tier distribution matching user intent.
            struct Cand { std::string key; nr::Tier from; nr::Tier to;
                          uint64_t dram_off; };
            std::vector<Cand> cands;
            cands.reserve(1024);
            tier.for_each([&](const std::string& k, const nr::ObjectMeta& m) {
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
    auto do_put = [&](const std::string& body, std::string* resp, bool high_prio) {
        // Parse optional tenant prefix ("T<id>:..."); default tenant=0.
        // We keep `body` unchanged and just remember where the "real" body
        // begins, so a 1 MB PUT does NOT pay the cost of copying the whole
        // buffer just to strip a tiny (or absent) prefix.
        size_t body_off = 0;
        uint32_t tid = parse_tenant_prefix(body, &body_off);
        // Enforce ACL: tenant must be whitelisted on this pool. The demo
        // pre-authorizes tenant=0 on default/slab1k at startup so the
        // existing, unprefixed traffic flows unchanged. Other tenants must
        // go through RPC_ISO_ALLOW first.
        if (!isolation.check(tid, "default/slab1k")) {
            char buf[128];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":false,\"err\":\"tenant %u not allowed on pool "
                "default/slab1k\"}", tid);
            resp->assign(buf, n);
            return;
        }
        std::string k, v;
        if (!parse_put_body(body, body_off, &k, &v)) {
            *resp = "{\"ok\":false,\"err\":\"bad put body\"}"; return;
        }
        if (v.size() > slab.slot_size()) {
            *resp = "{\"ok\":false,\"err\":\"value too large\"}"; return;
        }
        // QoS accounting: refill low-prio tokens (actual throttling happens
        // via QP selection + separate poll core).
        qos.on_submit(high_prio);
        // Fast path: try to speculatively allocate a slab slot for a new
        // key, then commit under a single TierEngine critical section. If
        // the key already existed, we just free back the speculation and
        // reuse the slot reported by reserve_or_reuse_slot.
        uint64_t off = 0; uint32_t old_sz = 0;
        void* spec_slot = slab.alloc();
        if (!spec_slot) {
            *resp = "{\"ok\":false,\"err\":\"slab oom\"}"; return;
        }
        uint64_t spec_off = (uint64_t)((char*)spec_slot - (char*)slab.base_addr());
        bool is_new = tier.reserve_or_reuse_slot(
            k, &off, &old_sz, spec_off, (uint32_t)v.size());
        void* slot = nullptr;
        if (is_new) {
            // Took ownership of the speculated slot.
            slot = spec_slot;
            off  = spec_off;
        } else {
            // Key already had a slot -> return speculation, use old offset.
            slab.free(spec_slot);
            slot = (char*)slab.base_addr() + off;
        }
        std::memcpy(slot, v.data(), v.size());

        // Replicate to peer at the SAME offset so primary & backup indices align.
        uint64_t remote_addr = peer.slab_base + off;
        uint64_t t0 = nr::now_ns();
        // QoS: pick a QP from the hi group for high-prio PUTs and from the
        // lo group otherwise. Hi gets exclusive QPs (less contention) and
        // its own CQ polling core.
        int qp_idx = qos.pick_qp(high_prio);

        // ---- High availability: skip cross-node replication when the peer
        // heartbeat has timed out. Without this, every PUT would block on
        // future.get() until the RDMA transport eventually errors out
        // (seconds to minutes), so the whole data plane would look frozen
        // from the client's point of view whenever the peer crashed. By
        // checking hb.peer_alive() upfront we degrade gracefully into
        // "local-only mode": PUTs land in the local slab + tier index, are
        // visible to local GETs immediately, and get counted into
        // degraded_puts. When the peer recovers, subsequent PUTs resume
        // full replication automatically -- no queueing, no bookkeeping,
        // per the project's "simple consistency" envelope. Durability
        // during the outage relies on the local slab + NVMe demote path.
        bool repl_ok;
        bool degraded = !hb.peer_alive();
        if (degraded) {
            // Local-only: no post, no wait, no wr_id reservation.
            repl_ok = true;
            degraded_puts.fetch_add(1, std::memory_order_relaxed);
            degraded_bytes.fetch_add(v.size(), std::memory_order_relaxed);
        } else {
            // W5 async replication: reserve a unique wr_id + future from the
            // shared poller thread BEFORE posting. Then post the WRITE (a
            // per-QP mutex inside RdmaCore serializes ibv_post_send) and wait
            // on the future. This removes the "N threads busy-polling the same
            // CQ and trampling each other's WCs" pathology that capped write
            // throughput at ~7 GB/s, and lets the full RDMA pipeline fill up.
            auto [wr_id, fut] = repl_waiter.reserve_wr_id();
            int rc = core.post_write(qp_idx, slot, v.size(), slab.lkey(),
                                     remote_addr, peer.slab_rkey,
                                     /*imm*/0, /*wr_id*/wr_id,
                                     /*signaled*/true);
            repl_ok = (rc == 0);
            if (repl_ok) {
                // Blocking wait for this specific WR's completion. The poller
                // thread delivers true on WC_SUCCESS, false otherwise.
                repl_ok = fut.get();
            } else {
                // Post failed -- the poller will never see this wr_id's WC.
                // Release the registered promise so the waiter map stays clean.
                repl_waiter.cancel_wr_id(wr_id);
            }
        }
        uint64_t dt = nr::now_ns() - t0;
        last_repl_ns.store(dt);
        lat_push(dt);
        busy_ns_1s.fetch_add(dt);
        if (repl_ok) {
            // Push index to peer so backup can serve local GET -- but only
            // when the peer is actually up; in degraded mode the SEND would
            // just fail and spam the log.
            if (!degraded) {
                send_kv_index(k, off, (uint32_t)v.size());
                bytes_tx_1s.fetch_add(v.size());
            }
            ops_put.fetch_add(1);
            // Attach route decision so the control plane can show which
            // node is *logically* primary / replica for this key. The
            // physical write path is currently "write local + replicate to
            // peer" regardless, but the router provides the sharding view
            // the demo needs to talk about load balance.
            auto rd = router.route(k);
            char buf[512];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":true,\"key\":\"%s\",\"size\":%zu,"
                "\"offset\":%lu,\"repl_ns\":%lu,\"degraded\":%s,"
                "\"route\":{\"primary\":\"%s\",\"replica\":\"%s\","
                "\"local_is_primary\":%s}}",
                k.c_str(), v.size(), (unsigned long)off, (unsigned long)dt,
                degraded ? "true" : "false",
                rd.primary.c_str(), rd.replica.c_str(),
                rd.local_is_primary ? "true" : "false");
            resp->assign(buf, n);
        } else {
            *resp = "{\"ok\":false,\"err\":\"replicate failed\"}";
        }
    };

    auto do_get = [&](const std::string& body, std::string* resp) {
        // Optional tenant prefix: same scheme as do_put (T<id>:key). When
        // absent, tenant=0 (default) is used.
        size_t body_off = 0;
        uint32_t tid = parse_tenant_prefix(body, &body_off);
        if (!isolation.check(tid, "default/slab1k")) {
            char buf[128];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":false,\"err\":\"tenant %u not allowed on pool "
                "default/slab1k\"}", tid);
            resp->assign(buf, n);
            return;
        }
        // Key extraction still needs a substring copy (downstream APIs take
        // std::string), but it only copies the key bytes (usually <64 B)
        // rather than the whole request body.
        std::string k = body.substr(body_off);
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

    // RPC_KV_GET_RAW: like RPC_KV_GET but returns the full payload verbatim
    // (no JSON encoding) so that nr_bench / perf_06 measurements reflect
    // the real bytes transferred over the UDS back to the client.
    // Wire: resp = [1 byte status][4 byte size][raw bytes ... size bytes]
    //   status = 1: OK,  0: not found.
    auto do_get_raw = [&](const std::string& body, std::string* resp) {
        // Mirror do_get: parse optional tenant prefix, enforce ACL. On
        // denial return the same 5-byte "not found" frame rather than a
        // JSON error, to keep the binary response framing consistent.
        size_t body_off = 0;
        uint32_t tid = parse_tenant_prefix(body, &body_off);
        if (!isolation.check(tid, "default/slab1k")) {
            resp->assign(5, '\0');  // status=0, size=0
            return;
        }
        std::string k = body.substr(body_off);
        nr::ObjectMeta meta{};
        if (!tier.get_meta_full(k, &meta)) {
            resp->assign(5, '\0');  // status=0, size=0
            return;
        }
        prefetcher.on_access(k);
        uint32_t sz = meta.size;
        if (meta.tier != nr::Tier::DRAM) {
            void* slot = slab.alloc();
            if (!slot) { resp->assign(5, '\0'); return; }
            uint64_t dram_off = (uint64_t)((char*)slot - (char*)slab.base_addr());
            if (!tier.promote(k, slot, dram_off)) {
                slab.free(slot); resp->assign(5, '\0'); return;
            }
            meta.offset = dram_off;
        }
        resp->resize(5 + sz);
        (*resp)[0] = 1;   // ok
        std::memcpy(&(*resp)[1], &sz, 4);
        std::memcpy(&(*resp)[5], (char*)slab.base_addr() + meta.offset, sz);
        ops_get.fetch_add(1);
        bytes_rx_1s.fetch_add(sz);
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
        // Reset prefetcher history/stats too.
        prefetcher.reset();
        char buf[128];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"freed_slabs\":%zu}", dram_offs.size());
        resp->assign(buf, n);
    };

    // RPC_SIM_RUN: synchronously run the discrete-event SimEngine and return
    // its speedup/throughput report. Body is a '&'-separated list of k=v
    // knobs, e.g. "entities=100000&events=1000000&threads=4&stress=32"
    // plus optional "capture_every_n=<N>" to control how often events are
    // pushed into SimCapture during the run (default 256).
    auto do_sim_run = [&](const std::string& body, std::string* resp) {
        nr::SimEngine::Config c;
        c.entities = 100000;
        c.events   = 1000000;
        c.threads  = 4;
        c.step_us  = 10;
        c.stress   = 32;
        c.capture_every_n = 256;
        auto parse_int = [&](const std::string& key) -> long long {
            auto p = body.find(key + "=");
            if (p == std::string::npos) return -1;
            p += key.size() + 1;
            auto e = body.find('&', p);
            std::string v = body.substr(p, e == std::string::npos ? body.size()-p : e-p);
            try { return std::stoll(v); } catch (...) { return -1; }
        };
        long long x;
        if ((x = parse_int("entities")) > 0) c.entities = (uint32_t)x;
        if ((x = parse_int("events"))   > 0) c.events   = (uint64_t)x;
        if ((x = parse_int("threads"))  > 0) c.threads  = (uint32_t)x;
        if ((x = parse_int("step_us"))  > 0) c.step_us  = (uint32_t)x;
        if ((x = parse_int("stress"))   > 0) c.stress   = (uint32_t)x;
        if ((x = parse_int("capture_every_n")) >= 0)
            c.capture_every_n = (uint32_t)x;

        // Snapshot capture counters before the run so we can report the
        // delta attributable to this specific simulation.
        auto cap_before = nr::SimCapture::instance().stats();

        nr::SimEngine eng;
        eng.init(c);
        auto r = eng.run();

        auto cap_after = nr::SimCapture::instance().stats();
        uint64_t cap_pushed  = cap_after.pushed_events - cap_before.pushed_events;
        uint64_t cap_dropped = cap_after.dropped_events - cap_before.dropped_events;

        char buf[640];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"entities\":%u,\"events\":%lu,\"threads\":%u,"
            "\"step_us\":%u,\"stress\":%u,\"wall_s\":%.6f,\"sim_s\":%.6f,"
            "\"speedup\":%.4f,\"events_per_sec\":%.0f,"
            "\"capture_every_n\":%u,\"captured_events\":%lu,"
            "\"captured_dropped\":%lu}",
            r.entities, (unsigned long)r.events, c.threads, c.step_us,
            c.stress, r.wall_s, r.sim_s, r.speedup, r.events_per_sec,
            c.capture_every_n,
            (unsigned long)cap_pushed, (unsigned long)cap_dropped);
        resp->assign(buf, n);
    };

    // RPC_ROUTE_QUERY: look up the route decision for a key without doing
    // any I/O. Body = raw key string. Used by the control plane / demo UI
    // to visualize which node would own each shard, and by tests to verify
    // the consistent-hash ring is populated consistently across both DPs.
    auto do_route_query = [&](const std::string& body, std::string* resp) {
        const std::string& k = body;
        auto rd = router.route(k);
        char buf[384];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"key\":\"%s\",\"primary\":\"%s\","
            "\"replica\":\"%s\",\"local_is_primary\":%s,\"self\":\"%s\"}",
            k.c_str(), rd.primary.c_str(), rd.replica.c_str(),
            rd.local_is_primary ? "true" : "false",
            args.self_ip.c_str());
        resp->assign(buf, n);
    };

    // ---------- SimCapture RPCs ----------
    // RPC_SIM_CAPTURE_STATS  body: (empty)
    //   -> returns counters (pushed / flushed / dropped).
    // RPC_SIM_CAPTURE_RESET  body: (empty)
    //   -> truncates the WAL and clears the counters; useful between
    //      demo takes so the numbers aren't cumulative from previous
    //      runs.
    auto do_sim_cap_stats = [&](const std::string& /*body*/, std::string* resp) {
        auto s = nr::SimCapture::instance().stats();
        char buf[384];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"pushed_events\":%lu,\"pushed_bytes\":%lu,"
            "\"flushed_events\":%lu,\"flushed_bytes\":%lu,"
            "\"dropped_events\":%lu}",
            (unsigned long)s.pushed_events,  (unsigned long)s.pushed_bytes,
            (unsigned long)s.flushed_events, (unsigned long)s.flushed_bytes,
            (unsigned long)s.dropped_events);
        resp->assign(buf, n);
    };

    auto do_sim_cap_reset = [&](const std::string& /*body*/, std::string* resp) {
        nr::SimCapture::instance().reset();
        *resp = "{\"ok\":true,\"action\":\"sim_capture_reset\"}";
    };

    // ---------- Isolation RPCs ----------
    // Wire format for both ALLOW/DENY bodies is "<tenant_id> <pool_name>".
    // Example body: "7 default/slab1k"
    //
    // These two RPCs are the only way to mutate the tenant ACL at runtime;
    // everything else (do_put / do_get / do_get_raw) just consults the
    // set via isolation.check(). The control plane (Flask) exposes them
    // as /api/iso/allow and /api/iso/deny for demo & automated testing.
    auto parse_iso_body = [](const std::string& body,
                             uint32_t* tid, std::string* pool) -> bool {
        auto sp = body.find(' ');
        if (sp == std::string::npos) return false;
        try { *tid = (uint32_t)std::stoul(body.substr(0, sp)); }
        catch (...) { return false; }
        *pool = body.substr(sp + 1);
        return !pool->empty();
    };

    auto do_iso_allow = [&](const std::string& body, std::string* resp) {
        uint32_t tid; std::string pool;
        if (!parse_iso_body(body, &tid, &pool)) {
            *resp = "{\"ok\":false,\"err\":\"bad iso body, expect '<tid> <pool>'\"}";
            return;
        }
        isolation.allow(tid, pool);
        char buf[192];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"action\":\"allow\",\"tenant_id\":%u,\"pool\":\"%s\"}",
            tid, pool.c_str());
        resp->assign(buf, n);
    };

    auto do_iso_deny = [&](const std::string& body, std::string* resp) {
        uint32_t tid; std::string pool;
        if (!parse_iso_body(body, &tid, &pool)) {
            *resp = "{\"ok\":false,\"err\":\"bad iso body, expect '<tid> <pool>'\"}";
            return;
        }
        isolation.deny(tid, pool);
        char buf[192];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"action\":\"deny\",\"tenant_id\":%u,\"pool\":\"%s\"}",
            tid, pool.c_str());
        resp->assign(buf, n);
    };

    auto do_iso_list = [&](const std::string& /*body*/, std::string* resp) {
        auto v = isolation.list_allowed();
        std::string out = "{\"ok\":true,\"allowed\":[";
        for (size_t i = 0; i < v.size(); ++i) {
            if (i) out.push_back(',');
            out.push_back('"');
            // list items are already "tid|pool" strings; JSON-escape '|'
            // is unnecessary, but we escape backslash/quote to be safe.
            for (char c : v[i]) {
                if (c == '"' || c == '\\') out.push_back('\\');
                out.push_back(c);
            }
            out.push_back('"');
        }
        out += "]}";
        *resp = std::move(out);
    };

    nr::UdsServer uds;
    uds.set_handler([&](const std::string& kind, const std::string& body,
                        std::string* resp) {
        if      (kind == "RPC_CLUSTER_STATUS") {
            char buf[384];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":true,\"self\":\"%s\",\"peer_alive\":%s,"
                "\"peer_slab_base\":%lu,\"peer_slab_rkey\":%u,\"peer_num_qp\":%u,"
                "\"degraded_puts\":%lu,\"degraded_bytes\":%lu}",
                args.role.c_str(),
                hb.peer_alive() ? "true" : "false",
                (unsigned long)peer.slab_base,
                peer.slab_rkey,
                (unsigned)peer.qpns.size(),
                (unsigned long)degraded_puts.load(),
                (unsigned long)degraded_bytes.load());
            resp->assign(buf, n);
        }
        else if (kind == "RPC_KV_PUT")     do_put(body, resp, /*high_prio*/true);
        else if (kind == "RPC_KV_PUT_HI")  do_put(body, resp, /*high_prio*/true);
        else if (kind == "RPC_KV_PUT_LO")  do_put(body, resp, /*high_prio*/false);
        else if (kind == "RPC_KV_GET")   do_get(body, resp);
        else if (kind == "RPC_KV_GET_RAW") do_get_raw(body, resp);
        else if (kind == "RPC_SNAPSHOT") do_snapshot(body, resp);
        else if (kind == "RPC_TIER_STATS")  do_tier_stats(resp);
        else if (kind == "RPC_TIER_DEMOTE") do_tier_demote(body, resp);
        else if (kind == "RPC_PREFETCH_STATS") do_prefetch_stats(body, resp);
        else if (kind == "RPC_COMPRESS_STATS") do_compress_stats(resp);
        else if (kind == "RPC_ADMIN_FLUSH")    do_admin_flush(resp);
        else if (kind == "RPC_SIM_RUN")        do_sim_run(body, resp);
        else if (kind == "RPC_ROUTE_QUERY")    do_route_query(body, resp);
        else if (kind == "RPC_SIM_CAPTURE_STATS") do_sim_cap_stats(body, resp);
        else if (kind == "RPC_SIM_CAPTURE_RESET") do_sim_cap_reset(body, resp);
        else if (kind == "RPC_ISO_ALLOW")       do_iso_allow(body, resp);
        else if (kind == "RPC_ISO_DENY")        do_iso_deny(body, resp);
        else if (kind == "RPC_ISO_LIST")        do_iso_list(body, resp);
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
    // Stop the replication poller BEFORE any remaining post path can try
    // to register a new future. It also releases any workers currently
    // stuck on fut.get() so they unwind cleanly.
    repl_waiter.stop();
    if (hb_thr.joinable()) hb_thr.join();
    if (metrics_thr.joinable()) metrics_thr.join();
    if (mig_thr.joinable())     mig_thr.join();
    batch.shutdown();
    // Final flush of the simulation capture WAL. stop() joins the bg
    // thread and writes any remaining buffered events.
    nr::SimCapture::instance().stop();
    io.shutdown();
    slab.shutdown();
    return 0;
}
