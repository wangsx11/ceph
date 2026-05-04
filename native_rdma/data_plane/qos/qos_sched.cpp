#include "qos_sched.h"
#include "../common/time_util.h"
#include "../common/logger.h"

#include <chrono>
#include <thread>

namespace nr {

bool QosSched::init(RdmaCore& core, const Config& cfg) {
    core_ = &core;
    cfg_  = cfg;
    if (cfg.hi_qp_count <= 0 || cfg.lo_qp_count <= 0) return false;
    if (cfg.hi_qp_start + cfg.hi_qp_count > core.num_qp()) return false;
    if (cfg.lo_qp_start + cfg.lo_qp_count > core.num_qp()) return false;
    lo_last_refill_ns_.store(now_ns(), std::memory_order_relaxed);
    lo_tokens_.store(cfg.lo_rate_limit_kops ? lo_token_cap() : 0, std::memory_order_relaxed);
    hi_recent_until_ns_.store(0, std::memory_order_relaxed);
    hi_rr_.store(0, std::memory_order_relaxed);
    lo_rr_.store(0, std::memory_order_relaxed);
    NR_INFO("QosSched ready: hi=[%d,%d) lo=[%d,%d) adaptive=1 lo_rate_kops=%u hi_window_us=%u lo_burst_ms=%u",
            cfg.hi_qp_start, cfg.hi_qp_start + cfg.hi_qp_count,
            cfg.lo_qp_start, cfg.lo_qp_start + cfg.lo_qp_count,
            cfg.lo_rate_limit_kops, cfg.hi_activity_window_us, cfg.lo_burst_ms);
    return true;
}

int QosSched::pick_qp(bool high_priority) {
    if (high_priority) {
        int idx = cfg_.hi_qp_start +
                  (hi_rr_.fetch_add(1, std::memory_order_relaxed) % cfg_.hi_qp_count);
        return idx;
    }
    int idx = cfg_.lo_qp_start +
              (lo_rr_.fetch_add(1, std::memory_order_relaxed) % cfg_.lo_qp_count);
    return idx;
}

int64_t QosSched::lo_token_cap() const {
    if (cfg_.lo_rate_limit_kops == 0 || cfg_.lo_burst_ms == 0) return 0;
    int64_t cap = ((int64_t)cfg_.lo_rate_limit_kops * 1000LL *
                   (int64_t)cfg_.lo_burst_ms) / 1000LL;
    return cap > 1 ? cap : 1;
}

void QosSched::on_submit(bool high_priority) {
    uint64_t now = now_ns();
    if (high_priority) {
        if (cfg_.lo_rate_limit_kops != 0 &&
            cfg_.hi_activity_window_us != 0 &&
            cfg_.lo_burst_ms != 0) {
            uint64_t until = now + (uint64_t)cfg_.hi_activity_window_us * 1000ULL;
            uint64_t cur = hi_recent_until_ns_.load(std::memory_order_relaxed);
            while (cur < until &&
                   !hi_recent_until_ns_.compare_exchange_weak(
                       cur, until, std::memory_order_relaxed)) {}
        }
        return;
    }

    if (cfg_.lo_rate_limit_kops == 0 ||
        cfg_.hi_activity_window_us == 0 ||
        cfg_.lo_burst_ms == 0) return;
    if (now > hi_recent_until_ns_.load(std::memory_order_relaxed)) return;

    // Lock-free fast path: try to consume a token atomically.
    // Only fall back to the refill+sleep path when tokens run out.
    int64_t t = lo_tokens_.fetch_sub(1, std::memory_order_relaxed);
    if (t > 0) return;  // got a token, proceed immediately

    // Slow path: refill and possibly sleep
    lo_tokens_.fetch_add(1, std::memory_order_relaxed); // undo the decrement
    const int64_t cap = lo_token_cap();
    while (true) {
        now = now_ns();
        if (now > hi_recent_until_ns_.load(std::memory_order_relaxed)) return;
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
