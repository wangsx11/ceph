#pragma once
#include "../rdma/rdma_core.h"
#include <atomic>
#include <cstdint>

namespace nr {

// Two-class adaptive QoS scheduler:
//  - High-priority requests use a dedicated QP group with its own poller core.
//  - Low-priority requests use their own QP group and are throttled only while
//    recent high-priority traffic is present.
class QosSched {
public:
    struct Config {
        int hi_qp_start = 0;
        int hi_qp_count = 2;
        int lo_qp_start = 2;
        int lo_qp_count = 6;
        uint32_t lo_rate_limit_kops = 160;     // protected low-priority rate; 0 = unlimited
        uint32_t hi_activity_window_us = 200000;
        uint32_t lo_burst_ms = 50;
    };
    bool init(RdmaCore& core, const Config& cfg);

    int  pick_qp(bool high_priority);   // returns qp_idx
    void on_submit(bool high_priority);

private:
    RdmaCore* core_ = nullptr;
    Config    cfg_;
    std::atomic<uint32_t> hi_rr_{0};
    std::atomic<uint32_t> lo_rr_{0};
    std::atomic<uint64_t> hi_recent_until_ns_{0};
    // Lock-free token bucket for low priority when high priority is active.
    std::atomic<int64_t>  lo_tokens_{0};
    std::atomic<uint64_t> lo_last_refill_ns_{0};

    int64_t lo_token_cap() const;
};

} // namespace nr
