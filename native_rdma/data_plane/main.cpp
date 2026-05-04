// native_rdma data-plane entry point.
// W2: full OOB handshake + real RDMA WRITE/READ + RDMA SEND heartbeat + real KV.

#include "common/logger.h"
#include "common/time_util.h"
#include "rdma/rdma_core.h"
#include "rdma/oob.h"
#include "rdma/repl_waiter.h"
#include "rdma/tcp_data_channel.h"
#include "gpu/gpu_direct.h"
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
#include <cerrno>
#include <thread>
#include <chrono>
#include <fstream>
#include <filesystem>
#include <mutex>
#include <vector>
#include <algorithm>
#include <unordered_map>
#include <unordered_set>
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
    uint16_t    tcp_data_port = 18516;   // TCP data-plane fallback port
    std::string transport  = "rdma";     // rdma | tcp | auto
    std::string uds_path   = "/tmp/native_rdma-dp.sock";
    std::string metrics_shm= "/tmp/native_rdma-metrics.shm";
    size_t      slab_bytes_1k = 1ULL * 1024 * 1024 * 1024;  // 1GB slab
    size_t      slab_slot_size = 1024;                      // W4 bw: configurable slot size
    std::string snap_dir   = "/dev/shm/native_rdma_snap";
    std::string backup_path= "/tmp/native_rdma_backup/pf7_backup.dat";
    uint64_t    backup_ring_bytes = 128ULL * 1024 * 1024;
    bool        backup_fsync = false;
    // W4: multi-tier storage backing paths.
    std::string nvme_path  = "/dev/shm/native_rdma_warm";
    std::string hdd_path   = "/dev/shm/native_rdma_cold";
    // M6 v2: heat-score tiering parameters. The migrator uses a decayed
    // activity score (see tier_engine.h) instead of raw idle windows.
    double      demote_hot_score  = 0.30;   // DRAM < cutoff -> NVMe
    double      demote_warm_score = 0.05;   // NVMe < cutoff -> HDD
    double      time_decay_alpha  = 0.10;   // score decay rate per second
    double      heat_score_init   = 1.0;    // score bump per access
    uint64_t    score_grace_ms    = 2000;   // new-object protection window
    int         migrate_interval_ms = 1000;
    size_t      migrate_batch_limit = 16;    // max background demotes per tick
    bool        async_repl = false;          // async replication: post WRITE but don't wait for completion
    bool        gdr_enable = false;           // enable GPUDirect RDMA endpoint on GPU-capable node
    size_t      gdr_bytes = 64ULL * 1024 * 1024;
    int         cuda_device = 0;
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
        else if (k == "--tcp-data-port") a.tcp_data_port = (uint16_t)std::stoi(v);
        else if (k == "--transport")   a.transport = v;
        else if (k == "--uds")         a.uds_path = v;
        else if (k == "--metrics-shm")a.metrics_shm = v;
        else if (k == "--snap-dir")    a.snap_dir = v;
        else if (k == "--backup-path") a.backup_path = v;
        else if (k == "--backup-ring-bytes") a.backup_ring_bytes = std::stoull(v);
        else if (k == "--backup-fsync") a.backup_fsync = (v.empty() || v == "1" || v == "true");
        else if (k == "--slab-slot-size") a.slab_slot_size = std::stoull(v);
        else if (k == "--slab-total-bytes") a.slab_bytes_1k = std::stoull(v);
        else if (k == "--nvme-path")  a.nvme_path = v;
        else if (k == "--hdd-path")   a.hdd_path = v;
        else if (k == "--demote-hot-score")  a.demote_hot_score  = std::stod(v);
        else if (k == "--demote-warm-score") a.demote_warm_score = std::stod(v);
        else if (k == "--time-decay-alpha")  a.time_decay_alpha  = std::stod(v);
        else if (k == "--heat-score-init")   a.heat_score_init   = std::stod(v);
        else if (k == "--score-grace-ms")    a.score_grace_ms    = std::stoull(v);
        else if (k == "--migrate-interval-ms") a.migrate_interval_ms = std::stoi(v);
        else if (k == "--migrate-batch-limit") a.migrate_batch_limit = std::stoull(v);
        else if (k == "--async-repl") a.async_repl = (v.empty() || v == "1" || v == "true");
        else if (k == "--gdr-enable") a.gdr_enable = (v.empty() || v == "1" || v == "true");
        else if (k == "--gdr-bytes") a.gdr_bytes = std::stoull(v);
        else if (k == "--cuda-device") a.cuda_device = std::stoi(v);
    }
    // Also check env var for convenience
    const char* ar_env = std::getenv("NR_ASYNC_REPL");
    if (ar_env && (std::string(ar_env) == "1" || std::string(ar_env) == "true"))
        a.async_repl = true;
    const char* tr_env = std::getenv("NR_TRANSPORT");
    if (tr_env && *tr_env) a.transport = tr_env;
    const char* tcp_port_env = std::getenv("NR_TCP_DATA_PORT");
    if (tcp_port_env && *tcp_port_env) a.tcp_data_port = (uint16_t)std::stoi(tcp_port_env);
    const char* gdr_env = std::getenv("NR_GDR_ENABLE");
    if (gdr_env && (std::string(gdr_env) == "1" || std::string(gdr_env) == "true"))
        a.gdr_enable = true;
    const char* gdr_bytes_env = std::getenv("NR_GDR_BYTES");
    if (gdr_bytes_env && *gdr_bytes_env) a.gdr_bytes = std::stoull(gdr_bytes_env);
    const char* cuda_dev_env = std::getenv("NR_CUDA_DEVICE");
    if (cuda_dev_env && *cuda_dev_env) a.cuda_device = std::stoi(cuda_dev_env);
    if (a.transport != "rdma" && a.transport != "tcp" && a.transport != "auto")
        a.transport = "rdma";
}

static void append_json_escaped(std::string* out, const std::string& v,
                                size_t max_len = 512) {
    size_t n = std::min(max_len, v.size());
    for (size_t i = 0; i < n; ++i) {
        char c = v[i];
        if (c == '"' || c == '\\') {
            out->push_back('\\');
            out->push_back(c);
        } else if ((unsigned char)c < 0x20) {
            out->push_back('?');
        } else {
            out->push_back(c);
        }
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

static std::string tenant_storage_key(uint32_t tenant_id,
                                      const std::string& logical_key) {
    if (tenant_id == 0) return logical_key;
    return "__tenant_" + std::to_string(tenant_id) + "__:" + logical_key;
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
// QP[0]:     replication (RDMA WRITE primary -> backup)
// QP[1]:     remote-read (RDMA READ)
// QP[0..21]: hi-prio data QPs (managed by QosSched)
// QP[22..28]:lo-prio data QPs (managed by QosSched)
// QP[29]:    batch aggregator
// QP[30]:    (reserved)
// QP[31]:    control/heartbeat (RDMA SEND/RECV)
static constexpr int QP_REPL = 0;
static constexpr int QP_READ = 1;
static constexpr int QP_HB   = 31;

int main(int argc, char** argv) {
    std::signal(SIGINT,  on_sig);
    std::signal(SIGTERM, on_sig);

    Args args; parse_args(argc, argv, args);
    NR_INFO("native_rdma_dp starting role=%s dev=%s gid_idx=%u self=%s peer=%s async_repl=%s transport=%s tcp_data_port=%u gdr_enable=%s cuda_device=%d gdr_bytes=%zu",
            args.role.c_str(), args.dev.c_str(), args.gid_idx,
            args.self_ip.c_str(), args.peer_ip.c_str(),
            args.async_repl ? "true" : "false",
            args.transport.c_str(), (unsigned)args.tcp_data_port,
            args.gdr_enable ? "true" : "false",
            args.cuda_device, args.gdr_bytes);

    // 1) RDMA core
    nr::RdmaCore core;
    nr::RdmaConfig rcfg;
    rcfg.dev_name  = args.dev;
    rcfg.gid_index = args.gid_idx;
    rcfg.num_qp    = 32;
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

    // Optional GPUDirect RDMA endpoint. In the current lab topology only node
    // B has NVIDIA GPUs, so B exposes a CUDA-allocated GPU MR and node A uses
    // the OOB metadata to RDMA WRITE/READ that MR.
    nr::GpuDirectBuffer gdr;
    bool gdr_requested_on_this_node = args.gdr_enable && args.role == "B";
    if (gdr_requested_on_this_node) {
        if (!nr::gpu_direct_compiled()) {
            NR_ERROR("NR_GDR_ENABLE=1 on role=B but binary was built with NR_USE_CUDA=OFF");
            return 4;
        }
        if (!gdr.init(core, args.cuda_device, args.gdr_bytes)) {
            NR_ERROR("GpuDirectBuffer init failed: %s", gdr.info().error.c_str());
            return 4;
        }
    } else if (args.gdr_enable) {
        NR_INFO("GDR requested but local role=%s does not expose a GPU MR", args.role.c_str());
    }

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
    nr::QosSched::Config qcfg; qcfg.hi_qp_start = 0; qcfg.hi_qp_count = 16;
    qcfg.lo_qp_start = 16;    qcfg.lo_qp_count = 13;
    // Adaptive QoS: low-priority traffic runs freely when there is no recent
    // high-priority pressure. Once high-priority PUTs arrive, low-priority is
    // shaped by a token bucket so it cannot occupy the replication path.
    // Optional env vars are kept for controlled experiments, not required by
    // the PF-3 acceptance script.
    const char* lo_env = std::getenv("NR_LO_RATE_KOPS");
    qcfg.lo_rate_limit_kops = lo_env ? (uint32_t)std::atoi(lo_env) : 160;
    const char* hi_win_env = std::getenv("NR_QOS_HI_WINDOW_US");
    qcfg.hi_activity_window_us = hi_win_env ? (uint32_t)std::atoi(hi_win_env) : 200000;
    const char* burst_env = std::getenv("NR_QOS_LO_BURST_MS");
    qcfg.lo_burst_ms = burst_env ? (uint32_t)std::atoi(burst_env) : 50;
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
    //   aggregator uses QP 29 and posts to its own CQ).
    //   Workers reserve a wr_id + future, post_write, then future.wait().
    //   This unlocks true post_send concurrency: at 1MB payload we go from
    //   ~7 GB/s with 8 threads to saturating the 100Gbps link.
    // NB: started AFTER oob_handshake below, so the poller only runs once
    //   QPs are in RTS and completions can actually be reaped.
    nr::ReplWaiter repl_waiter;

    nr::BatchAggregator batch;
    nr::BatchAggregator::Config bcfg; bcfg.qp_idx = 29;
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
    tcfg.demote_hot_score     = args.demote_hot_score;
    tcfg.demote_warm_score    = args.demote_warm_score;
    tcfg.time_decay_alpha     = args.time_decay_alpha;
    tcfg.heat_score_init      = args.heat_score_init;
    tcfg.score_grace_ns       = args.score_grace_ms * 1000000ULL;
    // NVMe/HDD 上每个对象占用的槽位大小。默认 1KB 对小对象够用，但演示 §6
    // 使用 4KB 对象，如果 tier_slot_size 仍然是 1KB，bump-pointer 每次只
    // 前进 1KB 而写入 4KB，就会发生对象之间相互覆盖、NVMe→HDD 二次下沉时
    // 读到错乱数据。解法：让 tier_slot_size 对齐到 slab_slot_size 的大小，
    // 这样 DRAM / NVMe / HDD 三层都使用同一槽位粒度。
    tcfg.tier_slot_size = args.slab_slot_size > tcfg.tier_slot_size
                        ? args.slab_slot_size : tcfg.tier_slot_size;
    tier.init(tcfg);

    // Prefetcher (W4 M1-3): stride + Markov-1 prediction over GET accesses.
    nr::Prefetcher prefetcher;
    prefetcher.init();
    std::atomic<uint64_t> prefetch_issued{0};
    std::atomic<uint64_t> prefetch_loaded{0};
    std::atomic<uint64_t> prefetch_hits{0};
    std::atomic<uint64_t> prefetch_already_hot{0};
    std::atomic<uint64_t> prefetch_skipped{0};
    std::mutex prefetched_mu;
    std::unordered_set<std::string> prefetched_keys;

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
    const auto& local_gpu = gdr.info();
    bool oob_ok = nr::oob_handshake(core,
        args.self_ip, args.peer_ip, args.data_port, is_listener,
        (uint64_t)slab.base_addr(),
        slab.capacity() * slab.slot_size(),
        slab.rkey(),
        local_gpu.enabled,
        local_gpu.base_addr,
        local_gpu.len,
        local_gpu.rkey,
        &peer);
    if (!oob_ok) {
        NR_ERROR("OOB handshake failed; exiting.");
        return 2;
    }

    // Register the peer's exported slab under the same logical pool name.
    // This gives the mempool namespace a concrete local+remote binding that
    // can be queried by functional tests instead of inferring naming solely
    // from raw OOB fields.
    nr::PoolInfo remote_pi;
    remote_pi.name      = "default/slab1k";
    remote_pi.base_addr = peer.slab_base;
    remote_pi.length    = peer.slab_len;
    remote_pi.rkey      = peer.slab_rkey;
    nr::PoolRegistry::instance().register_remote(args.peer_ip, remote_pi);

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

    // Mempool FN-4: adaptive remote/local placement metadata. Cold objects
    // inserted through RPC_MEMPOOL_ADAPT_PUT are placed in the peer slab by
    // RDMA WRITE first. Repeated reads cross a hot threshold and trigger an
    // RDMA READ into a local slab slot, after which normal RPC_KV_GET can
    // serve the object from local DRAM through TierEngine.
    struct AdaptiveObject {
        uint64_t remote_off = 0;
        uint64_t local_off = 0;
        uint32_t size = 0;
        uint32_t access_count = 0;
        bool localized = false;
        uint64_t write_ns = 0;
        uint64_t migrate_ns = 0;
    };
    constexpr uint32_t kAdaptiveHotThreshold = 3;
    std::mutex adaptive_mu;
    std::mutex adaptive_alloc_mu;
    std::unordered_map<std::string, AdaptiveObject> adaptive_index;
    uint64_t adaptive_next_remote_off = 0;
    std::atomic<uint64_t> adaptive_remote_puts{0};
    std::atomic<uint64_t> adaptive_remote_reads{0};
    std::atomic<uint64_t> adaptive_local_hits{0};
    std::atomic<uint64_t> adaptive_migrations{0};
    {
        uint64_t preferred = 64ULL * 1024 * 1024;
        if (peer.slab_len > preferred + slab.slot_size()) {
            adaptive_next_remote_off =
                (preferred / slab.slot_size()) * slab.slot_size();
        }
    }

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

    // 8b) Tier migrator thread (W4 / M6 v2):
    //
    // Every `migrate_interval_ms` we recompute each object's decayed heat
    // score (TierEngine::calc_heat_score) and demote those whose score has
    // fallen below the configured cutoff.  Promotion back up the hierarchy
    // is driven by actual reads on the GET path (see TierEngine::promote),
    // NOT by this thread.
    std::atomic<bool> mig_stop{false};
    std::atomic<uint64_t> mig_d_n_{0}, mig_n_h_{0};  // counters for stats RPC
    std::thread mig_thr([&]() {
        while (!mig_stop.load(std::memory_order_relaxed) &&
               !g_stop.load(std::memory_order_relaxed)) {
            std::this_thread::sleep_for(
                std::chrono::milliseconds(args.migrate_interval_ms));
            uint64_t now_n = nr::now_ns();
            const double   hot_cut   = args.demote_hot_score;
            const double   warm_cut  = args.demote_warm_score;
            const uint64_t grace_ns  = args.score_grace_ms * 1000000ULL;

            // Collect demotion candidates under index lock, then call
            // demote() after releasing the lock.  We scan the whole index
            // (demo scale is small, O(N) is cheap).
            struct Cand { std::string key; nr::Tier from; nr::Tier to;
                          uint64_t dram_off; double score; };
            std::vector<Cand> cands;
            cands.reserve(1024);
            tier.for_each([&](const std::string& k, const nr::ObjectMeta& m) {
                // Respect grace window for freshly-written objects so they
                // don't get demoted before the workload has a chance to
                // access them.
                if (m.birth_ns > 0 && now_n - m.birth_ns < grace_ns) return true;
                double s = tier.calc_heat_score(m, now_n);
                if (m.tier == nr::Tier::DRAM && s < hot_cut) {
                    // DRAM objects demote once their decayed score drops
                    // below `hot_cut`, regardless of read_cnt.
                    cands.push_back({k, nr::Tier::DRAM, nr::Tier::NVME,
                                     m.offset, s});
                } else if (m.tier == nr::Tier::NVME && s < warm_cut
                           && m.read_cnt == 0) {
                    // M6 v2 / W2 rule: an NVMe object may only descend to
                    // HDD if it was NEVER read since birth (read_cnt == 0).
                    // Objects that have any read history represent the
                    // "warm" tier and stay on NVMe permanently, which gives
                    // the demo a stable three-tier distribution.
                    cands.push_back({k, nr::Tier::NVME, nr::Tier::HDD, 0, s});
                }
                return true;
            });
            if (args.migrate_batch_limit > 0 &&
                cands.size() > args.migrate_batch_limit) {
                cands.resize(args.migrate_batch_limit);
            }
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

    auto apply_local_put = [&](const std::string& k, const std::string& v,
                               uint64_t* off_out, std::string* err) -> bool {
        if (v.size() > slab.slot_size()) {
            if (err) *err = "value too large";
            return false;
        }
        uint64_t off = 0; uint32_t old_sz = 0;
        void* spec_slot = slab.alloc();
        if (!spec_slot) {
            if (err) *err = "slab oom";
            return false;
        }
        uint64_t spec_off = (uint64_t)((char*)spec_slot - (char*)slab.base_addr());
        bool is_new = tier.reserve_or_reuse_slot(
            k, &off, &old_sz, spec_off, (uint32_t)v.size());
        void* slot = nullptr;
        if (is_new) {
            slot = spec_slot;
            off = spec_off;
        } else {
            slab.free(spec_slot);
            slot = (char*)slab.base_addr() + off;
        }
        std::memcpy(slot, v.data(), v.size());
        if (off_out) *off_out = off;
        return true;
    };

    auto read_local_value = [&](const std::string& k, std::string* value) -> bool {
        nr::ObjectMeta meta{};
        if (!tier.get_meta_full(k, &meta)) return false;
        if (meta.tier != nr::Tier::DRAM) {
            void* slot = slab.alloc();
            if (!slot) return false;
            uint64_t dram_off = (uint64_t)((char*)slot - (char*)slab.base_addr());
            if (!tier.promote(k, slot, dram_off)) {
                slab.free(slot);
                return false;
            }
            meta.offset = dram_off;
        } else {
            tier.on_access(k);
        }
        value->assign(meta.size, '\0');
        std::memcpy(value->data(), (char*)slab.base_addr() + meta.offset, meta.size);
        ops_get.fetch_add(1);
        bytes_rx_1s.fetch_add(meta.size);
        return true;
    };

    nr::TcpDataChannel tcp_data;
    nr::TcpDataChannel::Config tcp_cfg;
    tcp_cfg.self_ip = args.self_ip;
    tcp_cfg.peer_ip = args.peer_ip;
    tcp_cfg.port = args.tcp_data_port;
    bool tcp_data_ready = tcp_data.start(
        tcp_cfg,
        [&](const std::string& k, const std::string& v, std::string* err) -> bool {
            uint64_t off = 0;
            bool ok = apply_local_put(k, v, &off, err);
            if (ok) {
                ops_put.fetch_add(1);
                bytes_rx_1s.fetch_add(v.size());
                NR_INFO("TcpDataChannel PUT_REPL key=%s size=%zu off=%lu",
                        k.c_str(), v.size(), (unsigned long)off);
            }
            return ok;
        },
        [&](const std::string& k, std::string* value) -> bool {
            bool ok = read_local_value(k, value);
            if (ok) {
                NR_INFO("TcpDataChannel GET_REQ key=%s size=%zu",
                        k.c_str(), value->size());
            }
            return ok;
        });
    if (!tcp_data_ready) {
        NR_WARN("TcpDataChannel unavailable; TCP transport probes will fail");
    }

    // 9) UDS RPC handlers
    auto do_put = [&](const std::string& body, std::string* resp, bool high_prio,
                      const char* forced_transport) {
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
        std::string storage_k = tenant_storage_key(tid, k);
        // QoS accounting: high-priority PUTs mark a recent pressure window;
        // low-priority PUTs are throttled only while that window is active.
        qos.on_submit(high_prio);
        uint64_t off = 0;
        std::string local_err;
        if (!apply_local_put(storage_k, v, &off, &local_err)) {
            char buf[160];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":false,\"err\":\"%s\"}", local_err.c_str());
            resp->assign(buf, n);
            return;
        }
        void* slot = (char*)slab.base_addr() + off;

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
        bool repl_ok = false;
        bool used_tcp = false;
        std::string tcp_err;
        std::string desired_transport = forced_transport && *forced_transport
            ? forced_transport : args.transport;
        bool degraded = !hb.peer_alive();
        if (desired_transport == "tcp" || (desired_transport == "auto" && degraded)) {
            used_tcp = true;
            repl_ok = tcp_data_ready && tcp_data.put_peer(storage_k, v, &tcp_err);
            degraded = !repl_ok;
            if (!repl_ok) {
                degraded_puts.fetch_add(1, std::memory_order_relaxed);
                degraded_bytes.fetch_add(v.size(), std::memory_order_relaxed);
            }
        } else if (degraded) {
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
                if (args.async_repl) {
                    // Async mode: RDMA WRITE is posted and will complete in
                    // the background. The poller thread will reap the WC and
                    // fulfil the promise (cleaning up the waiter map entry).
                    // We don't block on fut.get(), so the PUT response is
                    // sent immediately after the local slab write.
                    (void)fut;  // future destructor is non-blocking
                } else {
                    // Sync mode: block until RDMA completion.
                    repl_ok = fut.get();
                }
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
            if (!degraded && !used_tcp) {
                send_kv_index(storage_k, off, (uint32_t)v.size());
                bytes_tx_1s.fetch_add(v.size());
            } else if (used_tcp && repl_ok) {
                bytes_tx_1s.fetch_add(v.size());
            }
            ops_put.fetch_add(1);
            // Attach route decision so the control plane can show which
            // node is *logically* primary / replica for this key. The
            // physical write path is currently "write local + replicate to
            // peer" regardless, but the router provides the sharding view
            // the demo needs to talk about load balance.
            auto rd = router.route(storage_k);
            char buf[896];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":true,\"key\":\"%s\",\"tenant_id\":%u,\"size\":%zu,"
                "\"offset\":%lu,\"repl_ns\":%lu,\"degraded\":%s,"
                "\"transport\":\"%s\",\"async_repl\":%s,\"tcp_data_ready\":%s,"
                "\"qos\":{\"priority\":\"%s\",\"qp_idx\":%d,"
                "\"hi_qp_start\":%d,\"hi_qp_count\":%d,"
                "\"lo_qp_start\":%d,\"lo_qp_count\":%d},"
                "\"route\":{\"primary\":\"%s\",\"replica\":\"%s\","
                "\"local_is_primary\":%s}}",
                k.c_str(), tid, v.size(), (unsigned long)off, (unsigned long)dt,
                degraded ? "true" : "false",
                used_tcp ? "tcp" : "rdma",
                args.async_repl ? "true" : "false",
                tcp_data_ready ? "true" : "false",
                high_prio ? "hi" : "lo",
                qp_idx,
                qcfg.hi_qp_start, qcfg.hi_qp_count,
                qcfg.lo_qp_start, qcfg.lo_qp_count,
                rd.primary.c_str(), rd.replica.c_str(),
                rd.local_is_primary ? "true" : "false");
            resp->assign(buf, n);
        } else {
            if (used_tcp) {
                char buf[256];
                int n = std::snprintf(buf, sizeof(buf),
                    "{\"ok\":false,\"err\":\"tcp replicate failed: %s\","
                    "\"transport\":\"tcp\",\"tcp_data_ready\":%s}",
                    tcp_err.c_str(), tcp_data_ready ? "true" : "false");
                resp->assign(buf, n);
            } else {
                *resp = "{\"ok\":false,\"err\":\"replicate failed\",\"transport\":\"rdma\"}";
            }
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
        std::string storage_k = tenant_storage_key(tid, k);
        nr::ObjectMeta meta{};
        if (!tier.get_meta_full(storage_k, &meta)) {
            *resp = "{\"ok\":false,\"err\":\"not found\"}";
            return;
        }
        {
            std::lock_guard<std::mutex> lk(prefetched_mu);
            auto it = prefetched_keys.find(storage_k);
            if (it != prefetched_keys.end()) {
                if (meta.tier == nr::Tier::DRAM) {
                    prefetched_keys.erase(it);
                    prefetch_hits.fetch_add(1, std::memory_order_relaxed);
                } else {
                    // The object was prefetched earlier but has since moved
                    // down again; drop the stale marker.
                    prefetched_keys.erase(it);
                }
            }
        }
        // Feed access history to prefetcher (before any promote).
        prefetcher.on_access(storage_k);
        auto prefetch_candidates = prefetcher.predict(storage_k);
        uint32_t sz = meta.size;
        const char* hit_kind = "local";
        if (meta.tier == nr::Tier::DRAM) {
            // DRAM hits are still real user reads.  They must refresh
            // heat_score/read_cnt; otherwise the M6 demo's hot/warm reads are
            // invisible to the tier migrator and every object looks cold.
            tier.on_access(storage_k);
        } else {
            // Cold hit: object lives on NVMe/HDD, promote it back to DRAM first.
            void* slot = slab.alloc();
            if (!slot) {
                *resp = "{\"ok\":false,\"err\":\"slab oom on promote\"}";
                return;
            }
            uint64_t dram_off = (uint64_t)((char*)slot - (char*)slab.base_addr());
            if (!tier.promote(storage_k, slot, dram_off)) {
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

        // Execute multi-strategy prefetch synchronously after the response has
        // been assembled. The predictor may return stride or Markov candidates;
        // for any candidate that currently lives below DRAM, we promote it into
        // a fresh slab slot so the next real GET can hit local memory.
        for (const auto& pk : prefetch_candidates) {
            if (pk.empty() || pk == storage_k) {
                prefetch_skipped.fetch_add(1, std::memory_order_relaxed);
                continue;
            }
            prefetch_issued.fetch_add(1, std::memory_order_relaxed);
            nr::ObjectMeta pm{};
            if (!tier.get_meta_full(pk, &pm)) {
                prefetch_skipped.fetch_add(1, std::memory_order_relaxed);
                continue;
            }
            if (pm.tier == nr::Tier::DRAM) {
                prefetch_already_hot.fetch_add(1, std::memory_order_relaxed);
                continue;
            }
            void* pslot = slab.alloc();
            if (!pslot) {
                prefetch_skipped.fetch_add(1, std::memory_order_relaxed);
                continue;
            }
            uint64_t poff = (uint64_t)((char*)pslot - (char*)slab.base_addr());
            if (!tier.promote(pk, pslot, poff)) {
                slab.free(pslot);
                prefetch_skipped.fetch_add(1, std::memory_order_relaxed);
                continue;
            }
            {
                std::lock_guard<std::mutex> lk(prefetched_mu);
                prefetched_keys.insert(pk);
            }
            prefetch_loaded.fetch_add(1, std::memory_order_relaxed);
        }
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
        std::string storage_k = tenant_storage_key(tid, k);
        nr::ObjectMeta meta{};
        if (!tier.get_meta_full(storage_k, &meta)) {
            resp->assign(5, '\0');  // status=0, size=0
            return;
        }
        prefetcher.on_access(storage_k);
        uint32_t sz = meta.size;
        if (meta.tier == nr::Tier::DRAM) {
            tier.on_access(storage_k);
        } else {
            void* slot = slab.alloc();
            if (!slot) { resp->assign(5, '\0'); return; }
            uint64_t dram_off = (uint64_t)((char*)slot - (char*)slab.base_addr());
            if (!tier.promote(storage_k, slot, dram_off)) {
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
        auto preds = prefetcher.predict(body, false);
        std::string out;
        char hdr[512];
        int n = std::snprintf(hdr, sizeof(hdr),
            "{\"ok\":true,\"total\":%lu,\"hits_stride\":%lu,\"hits_markov\":%lu,"
            "\"prefetch_issued\":%lu,\"prefetch_loaded\":%lu,"
            "\"prefetch_hits\":%lu,\"prefetch_already_hot\":%lu,"
            "\"prefetch_skipped\":%lu,"
            "\"query\":\"%s\",\"predicted\":[",
            (unsigned long)st.total_access,
            (unsigned long)st.hits_stride,
            (unsigned long)st.hits_markov,
            (unsigned long)prefetch_issued.load(),
            (unsigned long)prefetch_loaded.load(),
            (unsigned long)prefetch_hits.load(),
            (unsigned long)prefetch_already_hot.load(),
            (unsigned long)prefetch_skipped.load(),
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

    auto do_dedup_stats = [&](std::string* resp) {
        auto s = tier.dedup_stats();
        char buf[256];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"unique_objects\":%lu,\"duplicate_objects\":%lu,"
            "\"saved_bytes\":%lu,\"logical_bytes\":%lu}",
            (unsigned long)s.unique_objects,
            (unsigned long)s.duplicate_objects,
            (unsigned long)s.saved_bytes,
            (unsigned long)s.logical_bytes);
        resp->assign(buf, n);
    };

    auto do_io_stats = [&](std::string* resp) {
        auto s = io.stats();
        char buf[512];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"fg_read_ops\":%lu,\"fg_write_ops\":%lu,"
            "\"fg_read_bytes\":%lu,\"fg_write_bytes\":%lu,"
            "\"bg_read_ops\":%lu,\"bg_write_ops\":%lu,"
            "\"bg_read_bytes\":%lu,\"bg_write_bytes\":%lu}",
            (unsigned long)s.fg_read_ops,
            (unsigned long)s.fg_write_ops,
            (unsigned long)s.fg_read_bytes,
            (unsigned long)s.fg_write_bytes,
            (unsigned long)s.bg_read_ops,
            (unsigned long)s.bg_write_ops,
            (unsigned long)s.bg_read_bytes,
            (unsigned long)s.bg_write_bytes);
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
        prefetch_issued.store(0);
        prefetch_loaded.store(0);
        prefetch_hits.store(0);
        prefetch_already_hot.store(0);
        prefetch_skipped.store(0);
        {
            std::lock_guard<std::mutex> lk(prefetched_mu);
            prefetched_keys.clear();
        }
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
        c.entity_size = 1024;
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
        if ((x = parse_int("entity_size")) > 0) c.entity_size = (uint32_t)x;
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
            "{\"ok\":true,\"entities\":%u,\"entity_size\":%u,\"entity_bytes\":%lu,"
            "\"events\":%lu,\"threads\":%u,"
            "\"step_us\":%u,\"stress\":%u,\"wall_s\":%.6f,\"sim_s\":%.6f,"
            "\"speedup\":%.4f,\"events_per_sec\":%.0f,"
            "\"capture_every_n\":%u,\"captured_events\":%lu,"
            "\"captured_dropped\":%lu}",
            r.entities, r.entity_size, (unsigned long)r.entity_bytes,
            (unsigned long)r.events, c.threads, c.step_us,
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

    auto do_route_put = [&](const std::string& body, std::string* resp) {
        std::string k, v;
        if (!parse_put_body(body, &k, &v)) {
            *resp = "{\"ok\":false,\"err\":\"bad route put body\"}";
            return;
        }
        auto rd = router.route(k);
        uint64_t t0 = nr::now_ns();
        if (rd.local_is_primary) {
            uint64_t off = 0;
            std::string err;
            bool ok = apply_local_put(k, v, &off, &err);
            uint64_t dt = nr::now_ns() - t0;
            if (ok) {
                ops_put.fetch_add(1);
                char buf[512];
                int n = std::snprintf(buf, sizeof(buf),
                    "{\"ok\":true,\"key\":\"%s\",\"route_forwarded\":false,"
                    "\"forward_transport\":\"local\",\"primary\":\"%s\","
                    "\"replica\":\"%s\",\"local_is_primary\":true,"
                    "\"size\":%zu,\"offset\":%lu,\"route_ns\":%lu}",
                    k.c_str(), rd.primary.c_str(), rd.replica.c_str(),
                    v.size(), (unsigned long)off, (unsigned long)dt);
                resp->assign(buf, n);
            } else {
                char buf[256];
                int n = std::snprintf(buf, sizeof(buf),
                    "{\"ok\":false,\"err\":\"%s\",\"route_forwarded\":false,"
                    "\"forward_transport\":\"local\",\"primary\":\"%s\"}",
                    err.c_str(), rd.primary.c_str());
                resp->assign(buf, n);
            }
            return;
        }

        std::string err;
        bool ok = tcp_data_ready && tcp_data.put_peer(k, v, &err);
        uint64_t dt = nr::now_ns() - t0;
        if (ok) {
            bytes_tx_1s.fetch_add(v.size());
            char buf[512];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":true,\"key\":\"%s\",\"route_forwarded\":true,"
                "\"forward_transport\":\"tcp_data_channel\",\"primary\":\"%s\","
                "\"replica\":\"%s\",\"local_is_primary\":false,"
                "\"size\":%zu,\"route_ns\":%lu}",
                k.c_str(), rd.primary.c_str(), rd.replica.c_str(),
                v.size(), (unsigned long)dt);
            resp->assign(buf, n);
        } else {
            char buf[320];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":false,\"err\":\"route forward failed: %s\","
                "\"route_forwarded\":true,\"forward_transport\":\"tcp_data_channel\","
                "\"primary\":\"%s\",\"tcp_data_ready\":%s}",
                err.c_str(), rd.primary.c_str(),
                tcp_data_ready ? "true" : "false");
            resp->assign(buf, n);
        }
    };

    auto append_json_preview = [](std::string* out, const std::string& v) {
        size_t n = std::min<size_t>(64, v.size());
        for (size_t i = 0; i < n; ++i) {
            char c = v[i];
            if (c == '"' || c == '\\') { out->push_back('\\'); out->push_back(c); }
            else if ((unsigned char)c < 0x20) out->push_back('?');
            else out->push_back(c);
        }
    };

    auto do_tcp_get_peer = [&](const std::string& body, std::string* resp) {
        std::string value;
        std::string err;
        uint64_t t0 = nr::now_ns();
        bool ok = tcp_data_ready && tcp_data.get_peer(body, &value, &err);
        uint64_t dt = nr::now_ns() - t0;
        if (!ok) {
            std::string out = "{\"ok\":false,\"transport\":\"tcp\",\"err\":\"";
            append_json_preview(&out, err.empty() ? "tcp get peer failed" : err);
            out += "\",\"tcp_ns\":" + std::to_string(dt) + "}";
            *resp = std::move(out);
            return;
        }
        std::string out = "{\"ok\":true,\"transport\":\"tcp\",\"key\":\"";
        append_json_preview(&out, body);
        out += "\",\"size\":" + std::to_string(value.size()) + ",\"tcp_ns\":";
        out += std::to_string(dt);
        out += ",\"val\":\"";
        append_json_preview(&out, value);
        out += "\"}";
        *resp = std::move(out);
    };

    auto alloc_adaptive_remote = [&](uint32_t sz, uint64_t* remote_off) -> bool {
        if (sz == 0 || sz > slab.slot_size() || peer.slab_len == 0) {
            return false;
        }
        std::lock_guard<std::mutex> lk(adaptive_alloc_mu);
        uint64_t slot = slab.slot_size();
        uint64_t off = ((adaptive_next_remote_off + slot - 1) / slot) * slot;
        if (off + slot > peer.slab_len) {
            return false;
        }
        adaptive_next_remote_off = off + slot;
        *remote_off = off;
        return true;
    };

    auto rdma_read_peer_slab = [&](uint64_t remote_off, void* dst, uint32_t sz,
                                   uint64_t* read_ns) -> bool {
        auto [wr_id, fut] = repl_waiter.reserve_wr_id();
        uint64_t t0 = nr::now_ns();
        int rc = core.post_read(QP_READ, dst, sz, slab.lkey(),
                                peer.slab_base + remote_off,
                                peer.slab_rkey, wr_id);
        bool ok = false;
        if (rc == 0) {
            ok = fut.get();
        } else {
            repl_waiter.cancel_wr_id(wr_id);
        }
        *read_ns = nr::now_ns() - t0;
        return ok;
    };

    auto do_mempool_adapt_put = [&](const std::string& body, std::string* resp) {
        std::string k, v;
        if (!parse_put_body(body, &k, &v)) {
            *resp = "{\"ok\":false,\"err\":\"bad adaptive put body\"}";
            return;
        }
        if (!hb.peer_alive()) {
            *resp = "{\"ok\":false,\"err\":\"peer heartbeat is not alive\","
                    "\"placement\":\"local\",\"degraded\":true}";
            return;
        }
        if (v.empty() || v.size() > slab.slot_size()) {
            char buf[192];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":false,\"err\":\"value size must be in 1..slab_slot_size\","
                "\"size\":%zu,\"slab_slot_size\":%zu}",
                v.size(), slab.slot_size());
            resp->assign(buf, n);
            return;
        }
        {
            std::lock_guard<std::mutex> lk(adaptive_mu);
            if (adaptive_index.find(k) != adaptive_index.end()) {
                *resp = "{\"ok\":false,\"err\":\"adaptive key already exists\"}";
                return;
            }
        }
        uint64_t remote_off = 0;
        if (!alloc_adaptive_remote((uint32_t)v.size(), &remote_off)) {
            *resp = "{\"ok\":false,\"err\":\"adaptive remote slab allocation failed\"}";
            return;
        }
        void* src = slab.alloc();
        if (!src) {
            *resp = "{\"ok\":false,\"err\":\"slab oom for adaptive source\"}";
            return;
        }
        std::memcpy(src, v.data(), v.size());
        auto [wr_id, fut] = repl_waiter.reserve_wr_id();
        uint64_t t0 = nr::now_ns();
        int rc = core.post_write(QP_REPL, src, v.size(), slab.lkey(),
                                 peer.slab_base + remote_off,
                                 peer.slab_rkey, 0, wr_id, true);
        bool ok = false;
        if (rc == 0) {
            ok = fut.get();
        } else {
            repl_waiter.cancel_wr_id(wr_id);
        }
        uint64_t dt = nr::now_ns() - t0;
        slab.free(src);
        if (!ok) {
            char buf[192];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":false,\"err\":\"adaptive RDMA WRITE failed\","
                "\"post_rc\":%d,\"transport\":\"rdma\",\"degraded\":true}",
                rc);
            resp->assign(buf, n);
            return;
        }
        send_kv_index(k, remote_off, (uint32_t)v.size());
        {
            std::lock_guard<std::mutex> lk(adaptive_mu);
            adaptive_index[k] = AdaptiveObject{
                remote_off,
                0,
                (uint32_t)v.size(),
                0,
                false,
                dt,
                0,
            };
        }
        adaptive_remote_puts.fetch_add(1, std::memory_order_relaxed);
        ops_put.fetch_add(1, std::memory_order_relaxed);
        bytes_tx_1s.fetch_add(v.size(), std::memory_order_relaxed);
        last_repl_ns.store(dt);
        lat_push(dt);
        busy_ns_1s.fetch_add(dt);
        char buf[640];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"key\":\"%s\",\"policy\":\"cold_remote_first\","
            "\"placement\":\"remote\",\"placement_reason\":\"cold_object\","
            "\"transport\":\"rdma\",\"degraded\":false,\"local_cached\":false,"
            "\"size\":%zu,\"remote_offset\":%lu,\"remote_addr\":%lu,"
            "\"peer_slab_base\":%lu,\"peer_slab_rkey\":%u,"
            "\"write_ns\":%lu,\"hot_threshold\":%u}",
            k.c_str(), v.size(), (unsigned long)remote_off,
            (unsigned long)(peer.slab_base + remote_off),
            (unsigned long)peer.slab_base, peer.slab_rkey,
            (unsigned long)dt, kAdaptiveHotThreshold);
        resp->assign(buf, n);
    };

    auto do_mempool_adapt_get = [&](const std::string& body, std::string* resp) {
        const std::string& k = body;
        AdaptiveObject obj{};
        bool migrate = false;
        {
            std::lock_guard<std::mutex> lk(adaptive_mu);
            auto it = adaptive_index.find(k);
            if (it == adaptive_index.end()) {
                *resp = "{\"ok\":false,\"err\":\"adaptive key not found\"}";
                return;
            }
            it->second.access_count++;
            obj = it->second;
            migrate = !obj.localized && obj.access_count >= kAdaptiveHotThreshold;
        }
        if (obj.localized) {
            std::string val(obj.size, '\0');
            std::memcpy(val.data(), (char*)slab.base_addr() + obj.local_off, obj.size);
            tier.on_access(k);
            adaptive_local_hits.fetch_add(1, std::memory_order_relaxed);
            ops_get.fetch_add(1, std::memory_order_relaxed);
            bytes_rx_1s.fetch_add(obj.size, std::memory_order_relaxed);
            std::string out = "{\"ok\":true,\"key\":\"";
            append_json_preview(&out, k);
            out += "\",\"hit\":\"local_hot\",\"placement_before\":\"local\","
                   "\"placement_after\":\"local\",\"migrated\":false,"
                   "\"local_offset\":";
            out += std::to_string(obj.local_off);
            out += ",\"remote_offset\":";
            out += std::to_string(obj.remote_off);
            out += ",\"size\":";
            out += std::to_string(obj.size);
            out += ",\"access_count\":";
            out += std::to_string(obj.access_count);
            out += ",\"hot_threshold\":";
            out += std::to_string(kAdaptiveHotThreshold);
            out += ",\"val\":\"";
            append_json_preview(&out, val);
            out += "\"}";
            *resp = std::move(out);
            return;
        }

        void* dst = slab.alloc();
        if (!dst) {
            *resp = "{\"ok\":false,\"err\":\"slab oom for adaptive read\"}";
            return;
        }
        uint64_t read_ns = 0;
        bool ok = rdma_read_peer_slab(obj.remote_off, dst, obj.size, &read_ns);
        if (!ok) {
            slab.free(dst);
            *resp = "{\"ok\":false,\"err\":\"adaptive RDMA READ failed\","
                    "\"transport\":\"rdma\",\"degraded\":true}";
            return;
        }
        std::string val(obj.size, '\0');
        std::memcpy(val.data(), dst, obj.size);
        adaptive_remote_reads.fetch_add(1, std::memory_order_relaxed);
        ops_get.fetch_add(1, std::memory_order_relaxed);
        bytes_rx_1s.fetch_add(obj.size, std::memory_order_relaxed);

        if (!migrate) {
            slab.free(dst);
            std::string out = "{\"ok\":true,\"key\":\"";
            append_json_preview(&out, k);
            out += "\",\"hit\":\"remote_rdma_read\","
                   "\"placement_before\":\"remote\",\"placement_after\":\"remote\","
                   "\"migrated\":false,\"transport\":\"rdma\","
                   "\"remote_offset\":";
            out += std::to_string(obj.remote_off);
            out += ",\"size\":";
            out += std::to_string(obj.size);
            out += ",\"access_count\":";
            out += std::to_string(obj.access_count);
            out += ",\"hot_threshold\":";
            out += std::to_string(kAdaptiveHotThreshold);
            out += ",\"rdma_read_ns\":";
            out += std::to_string(read_ns);
            out += ",\"val\":\"";
            append_json_preview(&out, val);
            out += "\"}";
            *resp = std::move(out);
            return;
        }

        uint64_t local_off = (uint64_t)((char*)dst - (char*)slab.base_addr());
        tier.put_meta(k, local_off, obj.size);
        {
            std::lock_guard<std::mutex> lk(adaptive_mu);
            auto it = adaptive_index.find(k);
            if (it != adaptive_index.end()) {
                it->second.localized = true;
                it->second.local_off = local_off;
                it->second.migrate_ns = read_ns;
                obj = it->second;
            }
        }
        adaptive_migrations.fetch_add(1, std::memory_order_relaxed);
        std::string out = "{\"ok\":true,\"key\":\"";
        append_json_preview(&out, k);
        out += "\",\"hit\":\"remote_to_local_migrate\","
               "\"placement_before\":\"remote\",\"placement_after\":\"local\","
               "\"migrated\":true,\"transport\":\"rdma\","
               "\"remote_offset\":";
        out += std::to_string(obj.remote_off);
        out += ",\"local_offset\":";
        out += std::to_string(local_off);
        out += ",\"size\":";
        out += std::to_string(obj.size);
        out += ",\"access_count\":";
        out += std::to_string(obj.access_count);
        out += ",\"hot_threshold\":";
        out += std::to_string(kAdaptiveHotThreshold);
        out += ",\"rdma_read_ns\":";
        out += std::to_string(read_ns);
        out += ",\"val\":\"";
        append_json_preview(&out, val);
        out += "\"}";
        *resp = std::move(out);
    };

    auto do_mempool_adapt_stats = [&](std::string* resp) {
        uint64_t remote_objects = 0;
        uint64_t local_objects = 0;
        {
            std::lock_guard<std::mutex> lk(adaptive_mu);
            for (const auto& kv : adaptive_index) {
                if (kv.second.localized) ++local_objects;
                else ++remote_objects;
            }
        }
        char buf[384];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"hot_threshold\":%u,\"remote_objects\":%lu,"
            "\"local_objects\":%lu,\"remote_puts\":%lu,"
            "\"remote_reads\":%lu,\"local_hits\":%lu,\"migrations\":%lu}",
            kAdaptiveHotThreshold,
            (unsigned long)remote_objects,
            (unsigned long)local_objects,
            (unsigned long)adaptive_remote_puts.load(),
            (unsigned long)adaptive_remote_reads.load(),
            (unsigned long)adaptive_local_hits.load(),
            (unsigned long)adaptive_migrations.load());
        resp->assign(buf, n);
    };

    // ---------- SimCapture RPCs ----------
    // RPC_SIM_CAPTURE_STATS  body: (empty)
    //   -> returns counters, event-type counts, WAL size and WAL path.
    // RPC_SIM_CAPTURE_RESET  body: (empty)
    //   -> truncates the WAL and clears the counters; useful between
    //      demo takes so the numbers aren't cumulative from previous
    //      runs.
    auto do_sim_cap_stats = [&](const std::string& /*body*/, std::string* resp) {
        auto s = nr::SimCapture::instance().stats();
        char buf[640];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"pushed_events\":%lu,\"pushed_bytes\":%lu,"
            "\"flushed_events\":%lu,\"flushed_bytes\":%lu,"
            "\"dropped_events\":%lu,\"object_attr_events\":%lu,"
            "\"interaction_events\":%lu,\"wal_bytes\":%lu,"
            "\"wal_path\":\"%s\"}",
            (unsigned long)s.pushed_events,  (unsigned long)s.pushed_bytes,
            (unsigned long)s.flushed_events, (unsigned long)s.flushed_bytes,
            (unsigned long)s.dropped_events,
            (unsigned long)s.object_attr_events,
            (unsigned long)s.interaction_events,
            (unsigned long)s.wal_bytes,
            s.wal_path.c_str());
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

    auto do_mempool_pools = [&](const std::string& /*body*/, std::string* resp) {
        nr::PoolInfo local{};
        nr::PoolInfo remote{};
        bool local_ok = nr::PoolRegistry::instance().find_local("default/slab1k", &local);
        bool remote_ok = nr::PoolRegistry::instance().find_remote(
            args.peer_ip, "default/slab1k", &remote);
        char buf[1024];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":%s,\"self\":\"%s\",\"peer_id\":\"%s\","
            "\"local\":{\"ok\":%s,\"pool_id\":%u,\"name\":\"%s\","
            "\"base\":%lu,\"len\":%lu,\"lkey\":%u,\"rkey\":%u,"
            "\"tenant_id\":%u,\"numa\":%d},"
            "\"remote\":{\"ok\":%s,\"name\":\"%s\",\"base\":%lu,"
            "\"len\":%lu,\"rkey\":%u,\"tenant_id\":%u,\"numa\":%d}}",
            (local_ok && remote_ok) ? "true" : "false",
            args.role.c_str(), args.peer_ip.c_str(),
            local_ok ? "true" : "false",
            local.pool_id,
            local.name.c_str(),
            (unsigned long)local.base_addr,
            (unsigned long)local.length,
            local.lkey,
            local.rkey,
            local.tenant_id,
            local.numa,
            remote_ok ? "true" : "false",
            remote.name.c_str(),
            (unsigned long)remote.base_addr,
            (unsigned long)remote.length,
            remote.rkey,
            remote.tenant_id,
            remote.numa);
        resp->assign(buf, n);
    };

    int backup_fd = -1;
    std::mutex backup_mu;
    std::atomic<uint64_t> backup_next_off{0};
    auto do_backup_write = [&](const std::string& body, std::string* resp) {
        if (body.empty()) {
            *resp = "{\"ok\":false,\"err\":\"empty backup body\"}";
            return;
        }
        if (body.size() > (1U << 20)) {
            *resp = "{\"ok\":false,\"err\":\"backup body too large\"}";
            return;
        }

        {
            std::lock_guard<std::mutex> lk(backup_mu);
            if (backup_fd < 0) {
                std::filesystem::path p(args.backup_path);
                std::error_code ec;
                if (std::filesystem::exists(p, ec) && std::filesystem::is_directory(p, ec)) {
                    p /= "pf7_backup.dat";
                }
                if (p.has_parent_path()) {
                    std::filesystem::create_directories(p.parent_path(), ec);
                }
                backup_fd = ::open(p.c_str(), O_RDWR | O_CREAT, 0644);
                if (backup_fd < 0) {
                    char buf[192];
                    int n = std::snprintf(buf, sizeof(buf),
                        "{\"ok\":false,\"err\":\"open backup path failed errno=%d\"}",
                        errno);
                    resp->assign(buf, n);
                    return;
                }
                if (args.backup_ring_bytes > 0) {
                    if (::ftruncate(backup_fd, (off_t)args.backup_ring_bytes) != 0) {
                        NR_WARN("backup writer: ftruncate(%s, %lu) failed errno=%d",
                                p.c_str(), (unsigned long)args.backup_ring_bytes, errno);
                    }
                }
                NR_INFO("backup writer ready: path=%s fd=%d ring_bytes=%lu fsync=%s",
                        p.c_str(), backup_fd,
                        (unsigned long)args.backup_ring_bytes,
                        args.backup_fsync ? "true" : "false");
            }
        }

        uint64_t ring = args.backup_ring_bytes ? args.backup_ring_bytes : (128ULL << 20);
        if (ring < body.size()) ring = body.size();
        uint64_t raw_off = backup_next_off.fetch_add(body.size(), std::memory_order_relaxed);
        uint64_t off = raw_off % ring;
        if (off + body.size() > ring) off = 0;

        uint64_t t0 = nr::now_ns();
        ssize_t wr = ::pwrite(backup_fd, body.data(), body.size(), (off_t)off);
        int saved_errno = errno;
        int sync_rc = 0;
        if (wr == (ssize_t)body.size() && args.backup_fsync) {
            sync_rc = ::fdatasync(backup_fd);
            if (sync_rc != 0) saved_errno = errno;
        }
        uint64_t dt = nr::now_ns() - t0;

        if (wr != (ssize_t)body.size() || sync_rc != 0) {
            char buf[256];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":false,\"err\":\"backup write failed\",\"errno\":%d,"
                "\"written\":%ld,\"write_ns\":%lu}",
                saved_errno, (long)wr, (unsigned long)dt);
            resp->assign(buf, n);
            return;
        }

        char buf[256];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"bytes\":%zu,\"offset\":%lu,\"write_ns\":%lu,"
            "\"fsync\":%s}",
            body.size(), (unsigned long)off, (unsigned long)dt,
            args.backup_fsync ? "true" : "false");
        resp->assign(buf, n);
    };

    struct GdrReq {
        uint64_t offset = 0;
        size_t bytes = 4096;
        uint32_t seed = 0x5a;
    };
    auto parse_gdr_req = [](const std::string& body) {
        GdrReq req;
        size_t pos = 0;
        while (pos < body.size()) {
            size_t amp = body.find('&', pos);
            std::string item = body.substr(
                pos, amp == std::string::npos ? std::string::npos : amp - pos);
            size_t eq = item.find('=');
            if (eq != std::string::npos) {
                std::string key = item.substr(0, eq);
                std::string val = item.substr(eq + 1);
                try {
                    if (key == "offset") req.offset = std::stoull(val, nullptr, 0);
                    else if (key == "bytes" || key == "len") req.bytes = std::stoull(val, nullptr, 0);
                    else if (key == "seed") req.seed = (uint32_t)std::stoul(val, nullptr, 0);
                } catch (...) {
                    // Keep defaults on malformed fields; range checks below
                    // still reject unsafe requests.
                }
            }
            if (amp == std::string::npos) break;
            pos = amp + 1;
        }
        return req;
    };

    auto do_gdr_status = [&](std::string* resp) {
        const auto& gi = gdr.info();
        std::string out = "{\"ok\":true";
        out += ",\"gdr_requested\":";
        out += args.gdr_enable ? "true" : "false";
        out += ",\"gdr_compiled\":";
        out += nr::gpu_direct_compiled() ? "true" : "false";
        out += ",\"peer_memory_loaded\":";
        out += nr::gpu_peer_memory_loaded() ? "true" : "false";
        out += ",\"local_gpu_enabled\":";
        out += gi.enabled ? "true" : "false";
        out += ",\"local_gpu_device_id\":";
        out += std::to_string(gi.device_id);
        out += ",\"local_gpu_name\":\"";
        append_json_escaped(&out, gi.device_name);
        out += "\",\"local_gpu_base\":";
        out += std::to_string(gi.base_addr);
        out += ",\"local_gpu_len\":";
        out += std::to_string(gi.len);
        out += ",\"local_gpu_lkey\":";
        out += std::to_string(gi.lkey);
        out += ",\"local_gpu_rkey\":";
        out += std::to_string(gi.rkey);
        out += ",\"cuda_driver_version\":";
        out += std::to_string(gi.cuda_driver_version);
        out += ",\"cuda_runtime_version\":";
        out += std::to_string(gi.cuda_runtime_version);
        out += ",\"local_gpu_error\":\"";
        append_json_escaped(&out, gi.error);
        out += "\",\"peer_gpu_enabled\":";
        out += peer.gpu_enabled ? "true" : "false";
        out += ",\"peer_gpu_base\":";
        out += std::to_string(peer.gpu_base);
        out += ",\"peer_gpu_len\":";
        out += std::to_string(peer.gpu_len);
        out += ",\"peer_gpu_rkey\":";
        out += std::to_string(peer.gpu_rkey);
        out += "}";
        *resp = std::move(out);
    };

    auto do_gdr_write = [&](const std::string& body, std::string* resp) {
        GdrReq req = parse_gdr_req(body);
        if (!hb.peer_alive()) {
            *resp = "{\"ok\":false,\"err\":\"peer heartbeat is not alive\",\"degraded\":true}";
            return;
        }
        if (!peer.gpu_enabled || peer.gpu_base == 0 || peer.gpu_rkey == 0 || peer.gpu_len == 0) {
            *resp = "{\"ok\":false,\"err\":\"peer GPU MR is not available\",\"degraded\":true}";
            return;
        }
        if (req.bytes == 0 || req.bytes > slab.slot_size()) {
            char buf[192];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":false,\"err\":\"bytes must be in 1..slab_slot_size\","
                "\"requested\":%zu,\"slab_slot_size\":%zu}",
                req.bytes, slab.slot_size());
            resp->assign(buf, n);
            return;
        }
        if (req.offset > peer.gpu_len || req.bytes > peer.gpu_len - req.offset) {
            *resp = "{\"ok\":false,\"err\":\"write range exceeds peer GPU MR\"}";
            return;
        }
        void* slot = slab.alloc();
        if (!slot) {
            *resp = "{\"ok\":false,\"err\":\"slab oom\"}";
            return;
        }
        auto* p = static_cast<uint8_t*>(slot);
        for (size_t i = 0; i < req.bytes; ++i) {
            p[i] = nr::gdr_pattern_byte(req.offset + i, req.seed);
        }

        int qp_idx = QP_READ;
        auto [wr_id, fut] = repl_waiter.reserve_wr_id();
        uint64_t t0 = nr::now_ns();
        int rc = core.post_write(qp_idx, slot, req.bytes, slab.lkey(),
                                 peer.gpu_base + req.offset, peer.gpu_rkey,
                                 0, wr_id, true);
        bool ok = false;
        if (rc == 0) {
            ok = fut.get();
        } else {
            repl_waiter.cancel_wr_id(wr_id);
        }
        uint64_t dt = nr::now_ns() - t0;
        slab.free(slot);
        if (!ok) {
            char buf[192];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":false,\"err\":\"RDMA WRITE to peer GPU MR failed\","
                "\"post_rc\":%d,\"transport\":\"gpudirect_rdma\",\"degraded\":true}",
                rc);
            resp->assign(buf, n);
            return;
        }
        char buf[512];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":true,\"transport\":\"gpudirect_rdma\",\"degraded\":false,"
            "\"bytes\":%zu,\"offset\":%lu,\"seed\":%u,\"qp_idx\":%d,"
            "\"write_ns\":%lu,\"peer_gpu_base\":%lu,\"peer_gpu_rkey\":%u,"
            "\"peer_gpu_len\":%lu}",
            req.bytes, (unsigned long)req.offset, req.seed, qp_idx,
            (unsigned long)dt, (unsigned long)peer.gpu_base, peer.gpu_rkey,
            (unsigned long)peer.gpu_len);
        resp->assign(buf, n);
    };

    auto do_gdr_readback = [&](const std::string& body, std::string* resp) {
        GdrReq req = parse_gdr_req(body);
        if (!hb.peer_alive()) {
            *resp = "{\"ok\":false,\"err\":\"peer heartbeat is not alive\",\"degraded\":true}";
            return;
        }
        if (!peer.gpu_enabled || peer.gpu_base == 0 || peer.gpu_rkey == 0 || peer.gpu_len == 0) {
            *resp = "{\"ok\":false,\"err\":\"peer GPU MR is not available\",\"degraded\":true}";
            return;
        }
        if (req.bytes == 0 || req.bytes > slab.slot_size()) {
            char buf[192];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":false,\"err\":\"bytes must be in 1..slab_slot_size\","
                "\"requested\":%zu,\"slab_slot_size\":%zu}",
                req.bytes, slab.slot_size());
            resp->assign(buf, n);
            return;
        }
        if (req.offset > peer.gpu_len || req.bytes > peer.gpu_len - req.offset) {
            *resp = "{\"ok\":false,\"err\":\"read range exceeds peer GPU MR\"}";
            return;
        }
        void* slot = slab.alloc();
        if (!slot) {
            *resp = "{\"ok\":false,\"err\":\"slab oom\"}";
            return;
        }
        std::memset(slot, 0, req.bytes);
        int qp_idx = QP_READ;
        auto [wr_id, fut] = repl_waiter.reserve_wr_id();
        uint64_t t0 = nr::now_ns();
        int rc = core.post_read(qp_idx, slot, req.bytes, slab.lkey(),
                                peer.gpu_base + req.offset, peer.gpu_rkey,
                                wr_id);
        bool rdma_ok = false;
        if (rc == 0) {
            rdma_ok = fut.get();
        } else {
            repl_waiter.cancel_wr_id(wr_id);
        }
        uint64_t dt = nr::now_ns() - t0;
        if (!rdma_ok) {
            slab.free(slot);
            char buf[192];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":false,\"err\":\"RDMA READ from peer GPU MR failed\","
                "\"post_rc\":%d,\"transport\":\"gpudirect_rdma\",\"degraded\":true}",
                rc);
            resp->assign(buf, n);
            return;
        }
        auto* p = static_cast<uint8_t*>(slot);
        uint64_t checksum = 0;
        uint64_t mismatches = 0;
        uint64_t first_bad = UINT64_MAX;
        uint32_t expected_first = 0;
        uint32_t actual_first = 0;
        for (size_t i = 0; i < req.bytes; ++i) {
            uint8_t actual = p[i];
            uint8_t expected = nr::gdr_pattern_byte(req.offset + i, req.seed);
            checksum += actual;
            if (actual != expected) {
                if (first_bad == UINT64_MAX) {
                    first_bad = i;
                    expected_first = expected;
                    actual_first = actual;
                }
                ++mismatches;
            }
        }
        slab.free(slot);
        bool ok = mismatches == 0;
        char buf[640];
        int n = std::snprintf(buf, sizeof(buf),
            "{\"ok\":%s,\"transport\":\"gpudirect_rdma\",\"degraded\":false,"
            "\"bytes\":%zu,\"offset\":%lu,\"seed\":%u,\"qp_idx\":%d,"
            "\"read_ns\":%lu,\"checksum\":%lu,\"mismatches\":%lu,"
            "\"first_bad\":%lu,\"expected_first\":%u,\"actual_first\":%u}",
            ok ? "true" : "false", req.bytes, (unsigned long)req.offset,
            req.seed, qp_idx, (unsigned long)dt, (unsigned long)checksum,
            (unsigned long)mismatches, (unsigned long)first_bad,
            expected_first, actual_first);
        resp->assign(buf, n);
    };

    auto do_gdr_validate = [&](const std::string& body, std::string* resp) {
        GdrReq req = parse_gdr_req(body);
        auto r = gdr.validate_pattern(req.offset, req.bytes, req.seed);
        std::string out = "{\"ok\":";
        out += r.ok ? "true" : "false";
        out += ",\"gpu_side_validate\":true,\"bytes\":";
        out += std::to_string(r.bytes);
        out += ",\"offset\":";
        out += std::to_string(r.offset);
        out += ",\"seed\":";
        out += std::to_string(r.seed);
        out += ",\"checksum\":";
        out += std::to_string(r.checksum);
        out += ",\"mismatches\":";
        out += std::to_string(r.mismatches);
        out += ",\"first_bad\":";
        out += std::to_string(r.first_bad);
        out += ",\"expected_first\":";
        out += std::to_string(r.expected_first);
        out += ",\"actual_first\":";
        out += std::to_string(r.actual_first);
        out += ",\"validate_ns\":";
        out += std::to_string(r.validate_ns);
        out += ",\"local_gpu_enabled\":";
        out += gdr.info().enabled ? "true" : "false";
        out += ",\"local_gpu_rkey\":";
        out += std::to_string(gdr.info().rkey);
        out += ",\"err\":\"";
        append_json_escaped(&out, r.error);
        out += "\"}";
        *resp = std::move(out);
    };

    nr::UdsServer uds;
    uds.set_handler([&](const std::string& kind, const std::string& body,
                        std::string* resp) {
        if      (kind == "RPC_CLUSTER_STATUS") {
            const auto& gi = gdr.info();
            char buf[1280];
            int n = std::snprintf(buf, sizeof(buf),
                "{\"ok\":true,\"self\":\"%s\",\"peer_alive\":%s,"
                "\"local_slab_base\":%lu,\"local_slab_len\":%lu,"
                "\"local_slab_lkey\":%u,\"local_slab_rkey\":%u,"
                "\"peer_slab_base\":%lu,\"peer_slab_len\":%lu,"
                "\"peer_slab_rkey\":%u,\"peer_num_qp\":%u,"
                "\"local_gpu_enabled\":%s,\"local_gpu_len\":%lu,"
                "\"local_gpu_lkey\":%u,\"local_gpu_rkey\":%u,"
                "\"peer_gpu_enabled\":%s,\"peer_gpu_base\":%lu,"
                "\"peer_gpu_len\":%lu,\"peer_gpu_rkey\":%u,"
                "\"degraded_puts\":%lu,\"degraded_bytes\":%lu,"
                "\"transport\":\"%s\",\"async_repl\":%s,\"tcp_data_ready\":%s,"
                "\"tcp_data_port\":%u,\"tcp_puts_received\":%lu,"
                "\"tcp_gets_received\":%lu}",
                args.role.c_str(),
                hb.peer_alive() ? "true" : "false",
                (unsigned long)slab.base_addr(),
                (unsigned long)(slab.capacity() * slab.slot_size()),
                slab.lkey(),
                slab.rkey(),
                (unsigned long)peer.slab_base,
                (unsigned long)peer.slab_len,
                peer.slab_rkey,
                (unsigned)peer.qpns.size(),
                gi.enabled ? "true" : "false",
                (unsigned long)gi.len,
                gi.lkey,
                gi.rkey,
                peer.gpu_enabled ? "true" : "false",
                (unsigned long)peer.gpu_base,
                (unsigned long)peer.gpu_len,
                peer.gpu_rkey,
                (unsigned long)degraded_puts.load(),
                (unsigned long)degraded_bytes.load(),
                args.transport.c_str(),
                args.async_repl ? "true" : "false",
                tcp_data_ready ? "true" : "false",
                (unsigned)args.tcp_data_port,
                (unsigned long)tcp_data.puts_received(),
                (unsigned long)tcp_data.gets_received());
            resp->assign(buf, n);
        }
        else if (kind == "RPC_KV_PUT")     do_put(body, resp, /*high_prio*/true, "");
        else if (kind == "RPC_KV_PUT_HI")  do_put(body, resp, /*high_prio*/true, "");
        else if (kind == "RPC_KV_PUT_LO")  do_put(body, resp, /*high_prio*/false, "");
        else if (kind == "RPC_KV_PUT_TCP") do_put(body, resp, /*high_prio*/true, "tcp");
        else if (kind == "RPC_KV_PUT_RDMA") do_put(body, resp, /*high_prio*/true, "rdma");
        else if (kind == "RPC_KV_PUT_BATCH" || kind == "RPC_KV_PUT_BATCH_HI") {
            // Batch PUT: body = [u32 count]([u16 klen][key][u32 vlen][val])*
            // Three-phase batch: 1) parse all, 2) batch slab+tier, 3) RDMA.
            if (body.size() < 4) { *resp = "{\"ok\":false,\"err\":\"short batch\"}"; }
            else {
                uint32_t count = 0;
                std::memcpy(&count, body.data(), 4);
                if (count > 4096) count = 4096; // safety cap

                // Phase 1: parse all items from the wire buffer
                struct ParsedItem { std::string_view key; const char* vdata; uint32_t vlen; };
                std::vector<ParsedItem> parsed;
                parsed.reserve(count);
                size_t off = 4;
                for (uint32_t i = 0; i < count && off + 6 <= body.size(); ++i) {
                    uint16_t klen = 0;
                    std::memcpy(&klen, body.data() + off, 2); off += 2;
                    if (off + klen > body.size()) break;
                    std::string_view key(body.data() + off, klen); off += klen;
                    uint32_t vlen = 0;
                    std::memcpy(&vlen, body.data() + off, 4); off += 4;
                    if (off + vlen > body.size()) break;
                    const char* vdata = body.data() + off; off += vlen;
                    if (vlen <= slab.slot_size()) parsed.push_back({key, vdata, vlen});
                }
                uint32_t n_items = (uint32_t)parsed.size();

                // Phase 2a: batch slab alloc (single lock)
                std::vector<void*> slots(n_items);
                size_t n_alloc = slab.alloc_batch(slots.data(), n_items);

                // Phase 2b: batch tier reserve (single lock)
                std::vector<nr::TierEngine::BatchItem> tier_items(n_alloc);
                for (size_t i = 0; i < n_alloc; ++i) {
                    uint64_t spec_off = (uint64_t)((char*)slots[i] - (char*)slab.base_addr());
                    tier_items[i].key     = parsed[i].key;
                    tier_items[i].new_off = spec_off;
                    tier_items[i].new_size= parsed[i].vlen;
                }
                tier.batch_reserve_or_reuse(tier_items.data(), n_alloc);

                // Phase 3: resolve slots, memcpy, collect reused slots for batch free
                bool peer_alive = hb.peer_alive();
                uint32_t ok_n = 0;
                uint32_t degraded_n = 0;
                uint32_t replicated_n = 0;
                uint32_t repl_failed_n = 0;
                uint64_t repl_total_ns = 0;
                struct RdmaItem {
                    std::string key;
                    void* slot;
                    uint64_t slot_off;
                    uint32_t vlen;
                };
                std::vector<RdmaItem> rdma_items;
                if (peer_alive) rdma_items.reserve(n_alloc);
                std::vector<void*> free_slots;
                free_slots.reserve(n_alloc);
                for (size_t i = 0; i < n_alloc; ++i) {
                    auto& ti = tier_items[i];
                    void* slot;
                    uint64_t slot_off;
                    if (ti.is_new) {
                        slot = slots[i];
                        slot_off = ti.new_off;
                    } else {
                        free_slots.push_back(slots[i]);
                        slot = (char*)slab.base_addr() + ti.existing_off;
                        slot_off = ti.existing_off;
                    }
                    std::memcpy(slot, parsed[i].vdata, parsed[i].vlen);
                    if (!peer_alive) {
                        degraded_puts.fetch_add(1, std::memory_order_relaxed);
                        degraded_bytes.fetch_add(parsed[i].vlen, std::memory_order_relaxed);
                        ++degraded_n;
                    } else {
                        rdma_items.push_back({std::string(parsed[i].key), slot, slot_off, parsed[i].vlen});
                    }
                    ++ok_n;
                }
                // Batch free reused slots (single lock)
                if (!free_slots.empty())
                    slab.free_batch(free_slots.data(), free_slots.size());
                ops_put.fetch_add(ok_n);
                auto post_write_retry = [&](int qp_idx, void* slot, uint32_t vlen,
                                            uint64_t remote_addr, uint64_t wr_id,
                                            bool signaled) -> int {
                    int rc = 0;
                    for (int attempt = 0; attempt < 256; ++attempt) {
                        rc = core.post_write(qp_idx, slot, vlen, slab.lkey(),
                                             remote_addr, peer.slab_rkey, 0,
                                             wr_id, signaled);
                        if (rc == 0) return 0;
                        std::this_thread::yield();
                    }
                    return rc;
                };

                // Async replication: post all WRITEs, but only request CQEs for
                // each QP's tail WR in this batch. The unsignaled WRs are still
                // real RDMA WRITE operations; the signaled tail completion
                // proves that all earlier WRs on the same QP have retired.
                if (!rdma_items.empty() && args.async_repl) {
                    std::vector<int> item_qps(rdma_items.size(), 0);
                    std::vector<int> last_for_qp((size_t)core.num_qp(), -1);
                    for (size_t i = 0; i < rdma_items.size(); ++i) {
                        int qp_idx = qos.pick_qp(true);
                        item_qps[i] = qp_idx;
                        if (qp_idx >= 0 && qp_idx < core.num_qp()) {
                            last_for_qp[(size_t)qp_idx] = (int)i;
                        }
                    }
                    uint64_t t0 = nr::now_ns();
                    for (size_t i = 0; i < rdma_items.size(); ++i) {
                        auto& ri = rdma_items[i];
                        uint64_t remote_addr = peer.slab_base + ri.slot_off;
                        int qp_idx = item_qps[i];
                        bool signaled = (qp_idx >= 0 && qp_idx < core.num_qp() &&
                                         last_for_qp[(size_t)qp_idx] == (int)i);
                        uint64_t wr_id = 0;
                        if (signaled) {
                            auto reserved = repl_waiter.reserve_wr_id();
                            wr_id = reserved.first;
                        }
                        int rc = post_write_retry(qp_idx, ri.slot, ri.vlen,
                                                  remote_addr, wr_id, signaled);
                        if (rc != 0) {
                            if (signaled) repl_waiter.cancel_wr_id(wr_id);
                            ++repl_failed_n;
                        } else {
                            ++replicated_n;
                            send_kv_index(ri.key, ri.slot_off, ri.vlen);
                            bytes_tx_1s.fetch_add(ri.vlen);
                        }
                    }
                    repl_total_ns = nr::now_ns() - t0;
                } else if (!rdma_items.empty()) {
                    // Sync mode: per-item replication
                    for (auto& ri : rdma_items) {
                        int qp_idx = qos.pick_qp(true);
                        auto [wr_id, fut] = repl_waiter.reserve_wr_id();
                        uint64_t remote_addr = peer.slab_base + ri.slot_off;
                        uint64_t t0 = nr::now_ns();
                        int rc = core.post_write(qp_idx, ri.slot, ri.vlen,
                                                 slab.lkey(), remote_addr,
                                                 peer.slab_rkey, 0, wr_id, true);
                        bool repl_ok = false;
                        if (rc == 0) {
                            repl_ok = fut.get();
                        } else {
                            repl_waiter.cancel_wr_id(wr_id);
                        }
                        repl_total_ns += nr::now_ns() - t0;
                        if (repl_ok) {
                            ++replicated_n;
                            send_kv_index(ri.key, ri.slot_off, ri.vlen);
                            bytes_tx_1s.fetch_add(ri.vlen);
                        } else {
                            ++repl_failed_n;
                        }
                    }
                }
                if (repl_total_ns > 0) {
                    uint64_t avg_ns = repl_total_ns / std::max<size_t>(1, rdma_items.size());
                    last_repl_ns.store(avg_ns);
                    lat_push(avg_ns);
                    busy_ns_1s.fetch_add(repl_total_ns);
                }
                // Free slots for items we couldn't alloc
                bool ok = (ok_n == count && repl_failed_n == 0);
                bool degraded = (degraded_n > 0 || repl_failed_n > 0);
                char buf[256];
                int nb = std::snprintf(buf, sizeof(buf),
                    "{\"ok\":%s,\"n\":%u,\"ok_n\":%u,"
                    "\"peer_alive\":%s,\"replicated_n\":%u,"
                    "\"degraded_n\":%u,\"repl_failed_n\":%u,"
                    "\"degraded\":%s,\"transport\":\"rdma\","
                    "\"async_repl\":%s,\"aggregation\":\"batch_rpc\","
                    "\"repl_ns\":%lu}",
                    ok ? "true" : "false", count, ok_n,
                    peer_alive ? "true" : "false", replicated_n,
                    degraded_n, repl_failed_n,
                    degraded ? "true" : "false",
                    args.async_repl ? "true" : "false",
                    (unsigned long)repl_total_ns);
                resp->assign(buf, nb);
            }
        }
        else if (kind == "RPC_KV_GET")   do_get(body, resp);
        else if (kind == "RPC_KV_GET_RAW") do_get_raw(body, resp);
        else if (kind == "RPC_SNAPSHOT") do_snapshot(body, resp);
        else if (kind == "RPC_BACKUP_WRITE") do_backup_write(body, resp);
        else if (kind == "RPC_GDR_STATUS")   do_gdr_status(resp);
        else if (kind == "RPC_GDR_WRITE")    do_gdr_write(body, resp);
        else if (kind == "RPC_GDR_READBACK") do_gdr_readback(body, resp);
        else if (kind == "RPC_GDR_VALIDATE") do_gdr_validate(body, resp);
        else if (kind == "RPC_TIER_STATS")  do_tier_stats(resp);
        else if (kind == "RPC_TIER_DEMOTE") do_tier_demote(body, resp);
        else if (kind == "RPC_PREFETCH_STATS") do_prefetch_stats(body, resp);
        else if (kind == "RPC_COMPRESS_STATS") do_compress_stats(resp);
        else if (kind == "RPC_DEDUP_STATS")    do_dedup_stats(resp);
        else if (kind == "RPC_IO_STATS")       do_io_stats(resp);
        else if (kind == "RPC_ADMIN_FLUSH")    do_admin_flush(resp);
        else if (kind == "RPC_SIM_RUN")        do_sim_run(body, resp);
        else if (kind == "RPC_ROUTE_QUERY")    do_route_query(body, resp);
        else if (kind == "RPC_ROUTE_PUT")      do_route_put(body, resp);
        else if (kind == "RPC_TCP_GET_PEER")   do_tcp_get_peer(body, resp);
        else if (kind == "RPC_SIM_CAPTURE_STATS") do_sim_cap_stats(body, resp);
        else if (kind == "RPC_SIM_CAPTURE_RESET") do_sim_cap_reset(body, resp);
        else if (kind == "RPC_ISO_ALLOW")       do_iso_allow(body, resp);
        else if (kind == "RPC_ISO_DENY")        do_iso_deny(body, resp);
        else if (kind == "RPC_ISO_LIST")        do_iso_list(body, resp);
        else if (kind == "RPC_MEMPOOL_POOLS")   do_mempool_pools(body, resp);
        else if (kind == "RPC_MEMPOOL_ADAPT_PUT") do_mempool_adapt_put(body, resp);
        else if (kind == "RPC_MEMPOOL_ADAPT_GET") do_mempool_adapt_get(body, resp);
        else if (kind == "RPC_MEMPOOL_ADAPT_STATS") do_mempool_adapt_stats(resp);
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
    tcp_data.stop();
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
    if (backup_fd >= 0) ::close(backup_fd);
    io.shutdown();
    gdr.shutdown(core);
    slab.shutdown();
    return 0;
}
