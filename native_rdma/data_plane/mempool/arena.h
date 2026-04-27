#pragma once
#include "../rdma/rdma_core.h"
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <vector>

namespace nr {

// Best-fit arena for variable-size large objects (>= 64KB).
// Skeleton only; buddy allocator implementation will land later.
class Arena {
public:
    struct Config {
        size_t total_bytes = 256 * 1024 * 1024;
        int    numa_id     = -1;
        bool   use_hugepage= true;
    };
    bool  init(RdmaCore& core, const Config& cfg);
    void  shutdown();
    void* alloc(size_t size);
    void  free(void* p, size_t size);

    uint32_t rkey() const { return mr_.rkey; }
    uint32_t lkey() const { return mr_.lkey; }

private:
    Config     cfg_;
    MrHandle   mr_;
    size_t     bump_ = 0;  // TODO: replace with buddy allocator
    std::mutex mu_;
    RdmaCore*  core_ = nullptr;
};

} // namespace nr
