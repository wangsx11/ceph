#pragma once
#include "rdma_core.h"
#include <atomic>
#include <thread>
#include <functional>

namespace nr {

// Busy-poll CQ poller. One instance = one dedicated thread bound to a core.
// Callback is invoked for every completion; wc->wr_id carries user context.
class Poller {
public:
    using OnCompletion = std::function<void(const ibv_wc&)>;

    Poller(RdmaCore& core, int cq_idx, int bind_cpu);
    ~Poller();

    void set_callback(OnCompletion cb) { cb_ = std::move(cb); }
    void start();
    void stop();

private:
    void run();

    RdmaCore&          core_;
    int                cq_idx_;
    int                cpu_;
    std::atomic<bool>  running_{false};
    std::thread        th_;
    OnCompletion       cb_;
};

} // namespace nr
