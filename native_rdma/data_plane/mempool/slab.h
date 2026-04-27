#pragma once
#include "../rdma/rdma_core.h"
#include <cstdint>
#include <cstddef>
#include <vector>
#include <mutex>

namespace nr {

// Fixed-size slab allocator backed by a HugePage-registered MR.
// Lifetime: init() once at startup; alloc/free are O(1).
class SlabPool {
public:
    struct Config {
        size_t slot_size    = 1024;   // bytes per slot
        size_t total_bytes  = 64 * 1024 * 1024; // 64MB default
        int    numa_id      = -1;
        bool   use_hugepage = true;
    };

    bool init(RdmaCore& core, const Config& cfg);
    void shutdown();

    void*    alloc();
    void     free(void* p);

    // Accessors
    uint32_t rkey()       const { return mr_.rkey; }
    uint32_t lkey()       const { return mr_.lkey; }
    void*    base_addr()  const { return mr_.addr; }
    size_t   slot_size()  const { return cfg_.slot_size; }
    size_t   capacity()   const { return cfg_.total_bytes / cfg_.slot_size; }
    size_t   in_use()     const;

private:
    Config           cfg_;
    MrHandle         mr_;
    std::vector<uint32_t> free_list_; // indices of free slots (stack)
    mutable std::mutex mu_;
    RdmaCore*        core_ = nullptr;
};

} // namespace nr
