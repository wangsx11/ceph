#include "slab.h"
#include "../common/numa.h"
#include "../common/logger.h"

#include <cstring>
#include <cstdlib>

namespace nr {

static size_t round_up_2mb(size_t b) {
    const size_t p = 2ULL * 1024 * 1024;
    return (b + p - 1) & ~(p - 1);
}

bool SlabPool::init(RdmaCore& core, const Config& cfg) {
    core_ = &core;
    cfg_  = cfg;
    size_t bytes = round_up_2mb(cfg.total_bytes);

    void* p = nullptr;
    if (cfg.use_hugepage) {
        p = alloc_huge(bytes, cfg.numa_id);
    }
    if (!p) {
        // fallback to posix_memalign (4KB pages, no hugepage)
        if (posix_memalign(&p, 4096, bytes) != 0) p = nullptr;
    }
    if (!p) {
        NR_ERROR("SlabPool: allocate %zu bytes failed", bytes);
        return false;
    }
    std::memset(p, 0, bytes);

    mr_ = core_->reg_mr(p, bytes);
    if (!mr_.mr) {
        NR_ERROR("SlabPool: ibv_reg_mr failed");
        return false;
    }

    size_t n = bytes / cfg.slot_size;
    free_list_.reserve(n);
    // Free slots pushed in reverse so pop returns low indices first.
    for (size_t i = n; i > 0; --i) free_list_.push_back((uint32_t)(i - 1));

    NR_INFO("SlabPool ready: slot=%zu, total=%zu bytes, slots=%zu, rkey=0x%x",
            cfg.slot_size, bytes, n, mr_.rkey);
    return true;
}

void SlabPool::shutdown() {
    if (core_ && mr_.mr) core_->dereg_mr(mr_);
    if (mr_.addr) free_huge(mr_.addr, round_up_2mb(cfg_.total_bytes));
    mr_.addr = nullptr;
    free_list_.clear();
}

void* SlabPool::alloc() {
    std::lock_guard<std::mutex> lk(mu_);
    if (free_list_.empty()) return nullptr;
    uint32_t idx = free_list_.back();
    free_list_.pop_back();
    return (char*)mr_.addr + (size_t)idx * cfg_.slot_size;
}

size_t SlabPool::alloc_batch(void** out, size_t n) {
    std::lock_guard<std::mutex> lk(mu_);
    size_t got = std::min(n, free_list_.size());
    for (size_t i = 0; i < got; ++i) {
        uint32_t idx = free_list_.back();
        free_list_.pop_back();
        out[i] = (char*)mr_.addr + (size_t)idx * cfg_.slot_size;
    }
    return got;
}

void SlabPool::free(void* p) {
    if (!p) return;
    std::lock_guard<std::mutex> lk(mu_);
    size_t off = (char*)p - (char*)mr_.addr;
    uint32_t idx = (uint32_t)(off / cfg_.slot_size);
    free_list_.push_back(idx);
}

void SlabPool::free_batch(void** ptrs, size_t n) {
    std::lock_guard<std::mutex> lk(mu_);
    for (size_t i = 0; i < n; ++i) {
        if (!ptrs[i]) continue;
        size_t off = (char*)ptrs[i] - (char*)mr_.addr;
        free_list_.push_back((uint32_t)(off / cfg_.slot_size));
    }
}

size_t SlabPool::in_use() const {
    std::lock_guard<std::mutex> lk(mu_);
    return capacity() - free_list_.size();
}

} // namespace nr
