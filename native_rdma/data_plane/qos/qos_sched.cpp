#include "qos_sched.h"
#include "../common/time_util.h"
#include "../common/logger.h"

#include <chrono>
#include <thread>

namespace nr {

bool QosSched::init(RdmaCore& core, const Config& cfg) {
    core_ = &core;
    cfg_  = cfg;
    if (cfg.hi_qp_start + cfg.hi_qp_count > core.num_qp()) return false;
    if (cfg.lo_qp_start + cfg.lo_qp_count > core.num_qp()) return false;
    lo_last_refill_ns_.store(now_ns(), std::memory_order_relaxed);
    lo_tokens_.store(cfg.lo_rate_limit_kops ? (int64_t)cfg.lo_rate_limit_kops * 1000 : 0,
                     std::memory_order_relaxed);
    NR_INFO("QosSched ready: hi=[%d,%d) lo=[%d,%d) lo_rate_kops=%u",
            cfg.hi_qp_start, cfg.hi_qp_start + cfg.hi_qp_count,
            cfg.lo_qp_start, cfg.lo_qp_start + cfg.lo_qp_count,
            cfg.lo_rate_limit_kops);
    return true;
}

int QosSched::pick_qp(bool high_priority) {
    if (high_priority) {
        int idx = cfg_.hi_qp_start + (hi_rr_++ % cfg_.hi_qp_count);
        return idx;
    }
    int idx = cfg_.lo_qp_start + (lo_rr_++ % cfg_.lo_qp_count);
    return idx;
}

void QosSched::on_submit(bool high_priority) {
    if (high_priority || cfg_.lo_rate_limit_kops == 0) return;
    // Lock-free fast path: try to consume a token atomically.
    // Only fall back to the refill+sleep path when tokens run out.
    int64_t t = lo_tokens_.fetch_sub(1, std::memory_order_relaxed);
    if (t > 0) return;  // got a token, proceed immediately

    // Slow path: refill and possibly sleep
    lo_tokens_.fetch_add(1, std::memory_order_relaxed); // undo the decrement
    const int64_t cap = (int64_t)cfg_.lo_rate_limit_kops * 1000LL;
    while (true) {
        uint64_t now = now_ns();
        uint64_t last = lo_last_refill_ns_.load(std::memory_order_relaxed);
        uint64_t elapsed_ns = now - last;
        int64_t add = ((int64_t)cfg_.lo_rate_limit_kops * 1000LL * (int64_t)elapsed_ns)
                      / 1000000000LL;
        if (add > 0) {
            // Try to claim the refill (CAS on last_refill to avoid double-refill)
            if (lo_last_refill_ns_.compare_exchange_weak(last, now,
                    std::memory_order_relaxed)) {
                int64_t cur = lo_tokens_.fetch_add(add, std::memory_order_relaxed) + add;
                // Cap overflow
                if (cur > cap) {
                    lo_tokens_.fetch_sub(cur - cap, std::memory_order_relaxed);
                }
            }
        }
        // Try to consume again
        t = lo_tokens_.fetch_sub(1, std::memory_order_relaxed);
        if (t > 0) return;
        lo_tokens_.fetch_add(1, std::memory_order_relaxed);

        // Sleep briefly before retry
        uint64_t wait_ns = 1000000000ULL / ((uint64_t)cfg_.lo_rate_limit_kops * 1000ULL);
        if (wait_ns < 1000) wait_ns = 1000;
        wait_ns /= 4;
        std::this_thread::sleep_for(std::chrono::nanoseconds(wait_ns));
    }
}

} // namespace nr
