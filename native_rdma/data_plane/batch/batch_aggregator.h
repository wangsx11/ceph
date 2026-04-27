#pragma once
#include "../rdma/rdma_core.h"
#include "../common/mpsc_queue.h"
#include <cstdint>
#include <atomic>
#include <thread>

namespace nr {

// Aggregate small writes into a single WR linked-list post_send per tick
// to maximize doorbell efficiency.
class BatchAggregator {
public:
    struct Item {
        const void* buf;
        size_t      len;
        uint32_t    lkey;
        uint64_t    remote_addr;
        uint32_t    rkey;
        uint64_t    wr_id;
    };
    struct Config {
        int   qp_idx            = 0;
        int   max_batch         = 32;
        int   flush_interval_us = 10;
    };

    bool init(RdmaCore& core, const Config& cfg);
    void shutdown();

    // Non-blocking enqueue. Returns false if queue is full.
    bool submit(const Item& it);

private:
    void run();

    RdmaCore*        core_ = nullptr;
    Config           cfg_;
    MpscQueue<Item, 65536> q_;
    std::atomic<bool> running_{false};
    std::thread      th_;
};

} // namespace nr
