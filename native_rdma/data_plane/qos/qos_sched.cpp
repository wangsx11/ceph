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
    lo_last_refill_ns_ = now_ns();
    lo_tokens_ = cfg.lo_rate_limit_kops ? cfg.lo_rate_limit_kops * 1000 : 0;
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
    // Real throttling: lock, refill token bucket, wait for a token if none
    // are available. The lock also becomes a serialization point for the
    // low-priority class -- exactly what we want for docs/§7 row #3 where
    // high priority must beat low priority by >=22%.
    //
    // NB: use unique_lock (not lock_guard) because we need to .unlock()
    // while sleeping so other low-prio callers aren't blocked on us; the
    // destructor will then correctly decide based on the current lock
    // state instead of double-unlocking.
    std::unique_lock<std::mutex> lk(lo_mu_);
    const uint64_t cap = (uint64_t)cfg_.lo_rate_limit_kops * 1000ULL;
    while (true) {
        uint64_t t = now_ns();
        uint64_t elapsed_ns = t - lo_last_refill_ns_;
        uint64_t add = ((uint64_t)cfg_.lo_rate_limit_kops * 1000ULL * elapsed_ns)
                       / 1000000000ULL;
        if (add > 0) {
            lo_tokens_ += add;
            lo_last_refill_ns_ = t;
            if (lo_tokens_ > cap) lo_tokens_ = cap;
        }
        if (lo_tokens_ > 0) {
            --lo_tokens_;
            return;    // unique_lock dtor releases the lock.
        }
        // Not enough tokens: sleep briefly before retrying. Drop the lock
        // first so other low-prio callers can attempt a refill too.
        uint64_t wait_ns = 1000000000ULL / ((uint64_t)cfg_.lo_rate_limit_kops * 1000ULL);
        if (wait_ns < 1000) wait_ns = 1000;      // >= 1 us
        wait_ns /= 4;
        lk.unlock();
        std::this_thread::sleep_for(std::chrono::nanoseconds(wait_ns));
        lk.lock();
    }
}

} // namespace nr
