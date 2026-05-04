#include "slab.h"
#include "../common/numa.h"
#include "../common/logger.h"

#include <cstring>
#include <cstdlib>
#include <algorithm>
#include <unordered_map>

namespace nr {

namespace {

constexpr size_t kLocalRefill = 256;
constexpr size_t kLocalKeep = 256;
constexpr size_t kLocalMax = kLocalKeep + kLocalRefill;

struct LocalCache {
    uint64_t epoch = 0;
    std::vector<uint32_t> slots;
};

thread_local std::unordered_map<const SlabPool*, LocalCache> tls_caches;

LocalCache& cache_for(const SlabPool* pool, uint64_t epoch) {
    LocalCache& c = tls_caches[pool];
    if (c.epoch != epoch) {
        c.slots.clear();
        c.slots.reserve(kLocalMax);
        c.epoch = epoch;
    }
    return c;
}

} // namespace

static size_t round_up_2mb(size_t b) {
    const size_t p = 2ULL * 1024 * 1024;
    return (b + p - 1) & ~(p - 1);
}

bool SlabPool::init(RdmaCore& core, const Config& cfg) {
    core_ = &core;
    cfg_  = cfg;
    local_cached_.store(0, std::memory_order_relaxed);
    cache_epoch_.fetch_add(1, std::memory_order_acq_rel);
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
    cache_epoch_.fetch_add(1, std::memory_order_acq_rel);
    local_cached_.store(0, std::memory_order_relaxed);
    if (core_ && mr_.mr) core_->dereg_mr(mr_);
    if (mr_.addr) free_huge(mr_.addr, round_up_2mb(cfg_.total_bytes));
    mr_.addr = nullptr;
    free_list_.clear();
}

void* SlabPool::alloc() {
    LocalCache& cache = cache_for(this, cache_epoch_.load(std::memory_order_acquire));
    if (cache.slots.empty()) {
        std::lock_guard<std::mutex> lk(mu_);
        size_t got = std::min(kLocalRefill, free_list_.size());
        for (size_t i = 0; i < got; ++i) {
            cache.slots.push_back(free_list_.back());
            free_list_.pop_back();
        }
        local_cached_.fetch_add(got, std::memory_order_relaxed);
    }
    if (cache.slots.empty()) return nullptr;
    uint32_t idx = cache.slots.back();
    cache.slots.pop_back();
    local_cached_.fetch_sub(1, std::memory_order_relaxed);
    return (char*)mr_.addr + (size_t)idx * cfg_.slot_size;
}

size_t SlabPool::alloc_batch(void** out, size_t n) {
    size_t got = 0;
    LocalCache& cache = cache_for(this, cache_epoch_.load(std::memory_order_acquire));
    while (got < n && !cache.slots.empty()) {
        uint32_t idx = cache.slots.back();
        cache.slots.pop_back();
        local_cached_.fetch_sub(1, std::memory_order_relaxed);
        out[got++] = (char*)mr_.addr + (size_t)idx * cfg_.slot_size;
    }
    if (got == n) return got;

    std::lock_guard<std::mutex> lk(mu_);
    size_t from_global = std::min(n - got, free_list_.size());
    for (size_t i = 0; i < from_global; ++i) {
        uint32_t idx = free_list_.back();
        free_list_.pop_back();
        out[got++] = (char*)mr_.addr + (size_t)idx * cfg_.slot_size;
    }
    return got;
}

void SlabPool::free(void* p) {
    if (!p) return;
    size_t off = (char*)p - (char*)mr_.addr;
    uint32_t idx = (uint32_t)(off / cfg_.slot_size);
    LocalCache& cache = cache_for(this, cache_epoch_.load(std::memory_order_acquire));
    cache.slots.push_back(idx);
    local_cached_.fetch_add(1, std::memory_order_relaxed);
    if (cache.slots.size() > kLocalMax) {
        size_t ret = cache.slots.size() - kLocalKeep;
        std::lock_guard<std::mutex> lk(mu_);
        for (size_t i = 0; i < ret; ++i) {
            free_list_.push_back(cache.slots.back());
            cache.slots.pop_back();
        }
        local_cached_.fetch_sub(ret, std::memory_order_relaxed);
    }
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
    size_t global_free = free_list_.size();
    size_t local_free = local_cached_.load(std::memory_order_relaxed);
    size_t total_free = global_free + local_free;
    size_t cap = capacity();
    return total_free < cap ? cap - total_free : 0;
}

} // namespace nr
