#include "qos_sched.h"
#include "../common/time_util.h"
#include "../common/logger.h"

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
    // Simple token bucket refill.
    uint64_t t = now_ns();
    uint64_t elapsed_ns = t - lo_last_refill_ns_;
    uint64_t add = (cfg_.lo_rate_limit_kops * 1000ULL * elapsed_ns) / 1000000000ULL;
    if (add > 0) {
        lo_tokens_ += add;
        lo_last_refill_ns_ = t;
        if (lo_tokens_ > cfg_.lo_rate_limit_kops * 1000ULL)
            lo_tokens_ = cfg_.lo_rate_limit_kops * 1000ULL;
    }
    if (lo_tokens_ > 0) --lo_tokens_;
    // If tokens==0 the caller could back off; kept simple here.
}

} // namespace nr
