#pragma once
#include <atomic>
#include <cstdint>

namespace nr {

// Shared-memory metrics snapshot exposed to the Flask control plane.
// Updated every 100ms by MetricsAgent, read by Python side via mmap.
struct MetricsShared {
    std::atomic<uint64_t> ts_ns{0};
    std::atomic<uint64_t> ops_total{0};
    std::atomic<uint64_t> ops_hi{0};
    std::atomic<uint64_t> ops_lo{0};
    std::atomic<double>   bw_tx_gbps{0.0};
    std::atomic<double>   bw_rx_gbps{0.0};
    std::atomic<double>   rdma_util_pct{0.0};
    std::atomic<double>   lat_avg_us{0.0};
    std::atomic<double>   lat_p99_us{0.0};
    std::atomic<uint64_t> obj_dram{0};
    std::atomic<uint64_t> obj_nvme{0};
    std::atomic<uint64_t> obj_hdd{0};
    std::atomic<double>   replica_lag_us{0.0};
};

class MetricsAgent {
public:
    // Attach (or create) a shared-mem segment at `shm_path`.
    bool attach(const char* shm_path);
    MetricsShared* data() { return shm_; }

private:
    MetricsShared* shm_ = nullptr;
    int            fd_  = -1;
};

} // namespace nr
