// native_rdma data-plane entry point.
// Brings up RDMA core, mempools, storage, replication and API server.
// Real configuration will be loaded from deploy/node_{a,b}.env.

#include "common/logger.h"
#include "rdma/rdma_core.h"
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
#include <unistd.h>

static std::atomic<bool> g_stop{false};
static void on_sig(int) { g_stop.store(true); }

struct Args {
    std::string role       = "A";
    std::string self_ip;
    std::string peer_ip;
    std::string dev        = "mlx5_0";
    uint8_t     gid_idx    = 3;
    uint16_t    data_port  = 18515;
    std::string uds_path   = "/tmp/native_rdma-dp.sock";
    std::string metrics_shm= "/tmp/native_rdma-metrics.shm";
    size_t      slab_bytes_1k = 1ULL * 1024 * 1024 * 1024;  // 1GB slab
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
    }
}

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
    }

    // 3) Register local pool in registry
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

    // 5) Heartbeat
    nr::Heartbeat hb;
    hb.start(args.role == "A" ? "B" : "A", 1000, 3000);

    // 6) Metrics + UDS
    nr::MetricsAgent ma;
    ma.attach(args.metrics_shm.c_str());

    nr::UdsServer uds;
    uds.set_handler([&](const std::string& kind, const std::string& body,
                        std::string* resp) {
        // Minimal echo/stub dispatcher; full RPC in W2.
        (void)body;
        if (kind == "RPC_CLUSTER_STATUS") {
            *resp = "{\"self\":\"" + args.role + "\",\"ok\":true}";
        } else {
            *resp = "{\"ok\":true,\"kind\":\"" + kind + "\"}";
        }
    });
    uds.start(args.uds_path);

    NR_INFO("native_rdma_dp ready. Ctrl-C to exit.");
    while (!g_stop.load(std::memory_order_relaxed)) {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        tier.tick_migration();
        if (ma.data()) {
            ma.data()->obj_dram.store(tier.count(nr::Tier::DRAM));
            ma.data()->obj_nvme.store(tier.count(nr::Tier::NVME));
            ma.data()->obj_hdd.store(tier.count(nr::Tier::HDD));
        }
    }

    NR_INFO("native_rdma_dp shutting down...");
    uds.stop();
    hb.stop();
    batch.shutdown();
    slab.shutdown();
    return 0;
}
