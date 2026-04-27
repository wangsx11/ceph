#include "replicator.h"
#include "../common/time_util.h"
#include "../common/logger.h"

namespace nr {

bool Replicator::init(RdmaCore& core, const Config& cfg) {
    core_ = &core;
    cfg_  = cfg;
    NR_INFO("Replicator init qp=%d enable=%d", cfg.qp_idx, (int)cfg.enable);
    return true;
}

int64_t Replicator::replicate(const void* buf, size_t len, uint32_t lkey,
                              uint64_t remote_addr, uint32_t rkey, uint64_t wr_id)
{
    if (!cfg_.enable) return 0;
    uint64_t t0 = now_ns();
    int rc = core_->post_write(cfg_.qp_idx, buf, len, lkey,
                               remote_addr, rkey, 0, wr_id, true);
    if (rc != 0) { NR_WARN("replicate post failed rc=%d", rc); return -1; }
    // Poll until the WR we issued completes. Proper impl should use
    // per-wr_id mapping; here we assume a single in-flight replica for
    // simplicity (W2 will upgrade to pipelined).
    ibv_wc wc;
    while (true) {
        int n = core_->poll_cq(cfg_.qp_idx, &wc, 1);
        if (n < 0) return -1;
        if (n == 0) continue;
        if (wc.status != IBV_WC_SUCCESS) {
            NR_WARN("replicate WC err %d", wc.status);
            return -1;
        }
        break;
    }
    return (int64_t)(now_ns() - t0);
}

} // namespace nr
