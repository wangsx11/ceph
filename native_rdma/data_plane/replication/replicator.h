#pragma once
#include "../rdma/rdma_core.h"
#include <cstdint>
#include <string>

namespace nr {

// Synchronous primary-backup replicator.
// On put(), write local then issue a signaled RDMA WRITE to peer and wait.
class Replicator {
public:
    struct Config {
        int  qp_idx  = 0;
        bool enable  = true;
    };
    bool init(RdmaCore& core, const Config& cfg);
    // Returns replica latency in nanoseconds on success.
    int64_t replicate(const void* buf, size_t len, uint32_t lkey,
                      uint64_t remote_addr, uint32_t rkey, uint64_t wr_id);

private:
    RdmaCore* core_ = nullptr;
    Config    cfg_;
};

} // namespace nr
