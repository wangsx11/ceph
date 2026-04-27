#include "arena.h"
#include "../common/numa.h"
#include "../common/logger.h"

#include <cstring>
#include <cstdlib>

namespace nr {

static size_t round_up_2mb(size_t b) {
    const size_t p = 2ULL * 1024 * 1024;
    return (b + p - 1) & ~(p - 1);
}

bool Arena::init(RdmaCore& core, const Config& cfg) {
    core_ = &core;
    cfg_  = cfg;
    size_t bytes = round_up_2mb(cfg.total_bytes);
    void*  p = cfg.use_hugepage ? alloc_huge(bytes, cfg.numa_id) : nullptr;
    if (!p) { if (posix_memalign(&p, 4096, bytes) != 0) p = nullptr; }
    if (!p) { NR_ERROR("Arena: alloc %zu failed", bytes); return false; }
    std::memset(p, 0, bytes);
    mr_ = core_->reg_mr(p, bytes);
    if (!mr_.mr) { NR_ERROR("Arena: reg_mr failed"); return false; }
    bump_ = 0;
    NR_INFO("Arena ready: %zu bytes, rkey=0x%x", bytes, mr_.rkey);
    return true;
}

void Arena::shutdown() {
    if (core_ && mr_.mr) core_->dereg_mr(mr_);
    if (mr_.addr) free_huge(mr_.addr, round_up_2mb(cfg_.total_bytes));
    mr_.addr = nullptr;
}

void* Arena::alloc(size_t size) {
    std::lock_guard<std::mutex> lk(mu_);
    size = (size + 63) & ~((size_t)63); // 64B align
    if (bump_ + size > mr_.length) return nullptr;
    void* p = (char*)mr_.addr + bump_;
    bump_ += size;
    return p;
}

void Arena::free(void* /*p*/, size_t /*size*/) {
    // Bump allocator; freeing is a no-op for now. Replace with buddy later.
}

} // namespace nr
