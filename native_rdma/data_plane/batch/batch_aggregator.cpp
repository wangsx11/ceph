#include "batch_aggregator.h"
#include "../common/time_util.h"
#include "../common/logger.h"

#include <cstring>
#include <vector>

namespace nr {

bool BatchAggregator::init(RdmaCore& core, const Config& cfg) {
    core_ = &core;
    cfg_  = cfg;
    running_.store(true);
    th_ = std::thread(&BatchAggregator::run, this);
    NR_INFO("BatchAggregator started: qp=%d max_batch=%d interval=%dus",
            cfg.qp_idx, cfg.max_batch, cfg.flush_interval_us);
    return true;
}

void BatchAggregator::shutdown() {
    if (!running_.exchange(false)) return;
    if (th_.joinable()) th_.join();
}

bool BatchAggregator::submit(const Item& it) {
    return q_.push(it);
}

void BatchAggregator::run() {
    std::vector<ibv_send_wr> wrs;
    std::vector<ibv_sge>     sges;
    wrs.reserve(cfg_.max_batch);
    sges.reserve(cfg_.max_batch);

    uint64_t last_flush_ns = now_ns();
    Item it;
    while (running_.load(std::memory_order_relaxed)) {
        int n = 0;
        while (n < cfg_.max_batch && q_.pop(it)) {
            ibv_sge sge{(uint64_t)it.buf, (uint32_t)it.len, it.lkey};
            sges.push_back(sge);
            ibv_send_wr wr{};
            wr.wr_id      = it.wr_id;
            wr.num_sge    = 1;
            wr.opcode     = IBV_WR_RDMA_WRITE;
            wr.send_flags = 0; // unsignaled for intermediate WRs
            wr.wr.rdma.remote_addr = it.remote_addr;
            wr.wr.rdma.rkey        = it.rkey;
            wrs.push_back(wr);
            ++n;
        }

        uint64_t now = now_ns();
        bool timeout = (now - last_flush_ns) >=
                       (uint64_t)cfg_.flush_interval_us * 1000ULL;
        if (n > 0 && (n >= cfg_.max_batch || timeout)) {
            // link SGEs -> WRs and chain WR next
            for (int i = 0; i < n; ++i) {
                wrs[i].sg_list = &sges[i];
                wrs[i].next    = (i + 1 < n) ? &wrs[i + 1] : nullptr;
            }
            // Signal only the last WR to reduce CQ pressure.
            wrs[n - 1].send_flags = IBV_SEND_SIGNALED;
            ibv_send_wr* bad = nullptr;
            int rc = core_->post_send_batch(cfg_.qp_idx, &wrs[0], &bad);
            if (rc != 0) {
                NR_WARN("batch post_send failed rc=%d bad_wr=%p", rc, (void*)bad);
            }
            wrs.clear();
            sges.clear();
            last_flush_ns = now;
        }
        // Very light spin; avoids 100% CPU when queue empty.
        if (n == 0) {
            __asm__ __volatile__("pause" ::: "memory");
        }
    }
}

} // namespace nr
