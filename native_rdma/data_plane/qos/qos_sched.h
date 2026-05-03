#pragma once
#include "../rdma/rdma_core.h"
#include <atomic>
#include <cstdint>

namespace nr {

// Simple two-class QoS scheduler:
//  - High-priority requests use a dedicated QP group with its own poller core.
//  - Low-priority requests share the rest of QPs and are rate-limited.
class QosSched {
public:
    struct Config {
        int hi_qp_start = 0;
        int hi_qp_count = 2;
        int lo_qp_start = 2;
        int lo_qp_count = 6;
        uint32_t lo_rate_limit_kops = 0;  // 0 = unlimited
    };
    bool init(RdmaCore& core, const Config& cfg);

    int  pick_qp(bool high_priority);   // returns qp_idx
    void on_submit(bool high_priority);

private:
    RdmaCore* core_ = nullptr;
    Config    cfg_;
    uint32_t  hi_rr_ = 0;
    uint32_t  lo_rr_ = 0;
    // Lock-free token bucket for low priority.
    std::atomic<int64_t>  lo_tokens_{0};
    std::atomic<uint64_t> lo_last_refill_ns_{0};
};

} // namespace nr
