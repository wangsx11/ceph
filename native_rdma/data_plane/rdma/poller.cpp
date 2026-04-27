#include "poller.h"
#include "../common/numa.h"
#include "../common/logger.h"

namespace nr {

Poller::Poller(RdmaCore& core, int cq_idx, int bind_cpu)
    : core_(core), cq_idx_(cq_idx), cpu_(bind_cpu) {}

Poller::~Poller() { stop(); }

void Poller::start() {
    if (running_.exchange(true)) return;
    th_ = std::thread(&Poller::run, this);
}

void Poller::stop() {
    if (!running_.exchange(false)) return;
    if (th_.joinable()) th_.join();
}

void Poller::run() {
    if (cpu_ >= 0) {
        if (!bind_thread_to_cpu(cpu_)) {
            NR_WARN("poller: failed to bind cpu %d", cpu_);
        } else {
            NR_INFO("poller: bound to cpu %d, cq_idx=%d", cpu_, cq_idx_);
        }
    }
    constexpr int BATCH = 32;
    ibv_wc wcs[BATCH];
    while (running_.load(std::memory_order_relaxed)) {
        int n = core_.poll_cq(cq_idx_, wcs, BATCH);
        if (n > 0 && cb_) {
            for (int i = 0; i < n; ++i) cb_(wcs[i]);
        }
        // busy loop; no sleep to hit μs latency.
    }
}

} // namespace nr
