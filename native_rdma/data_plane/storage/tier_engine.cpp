#include "tier_engine.h"
#include "io_scheduler.h"
#include "../common/logger.h"
#include "../common/time_util.h"

#include <algorithm>
#include <cstring>

namespace nr {

bool TierEngine::init(const Config& cfg) {
    cfg_ = cfg;
    NR_INFO("TierEngine init: nvme=%s hdd=%s dram_cap=%zuMB "
            "nvme_cap=%zuMB hdd_cap=%zuMB demote_idle=%llu/%llu ns",
            cfg.nvme_path.c_str(), cfg.hdd_path.c_str(),
            cfg.dram_cap_bytes / (1024ULL * 1024),
            cfg.nvme_cap_bytes / (1024ULL * 1024),
            cfg.hdd_cap_bytes  / (1024ULL * 1024),
            (unsigned long long)cfg.dram_demote_idle_ns,
            (unsigned long long)cfg.nvme_demote_idle_ns);
    return true;
}

void TierEngine::shutdown() {}

bool TierEngine::put(std::string_view key, std::string_view val, uint8_t /*prio*/) {
    std::lock_guard<std::mutex> lk(mu_);
    auto& m = index_[std::string(key)];
    bool was_new = (m.size == 0);
    m.size       = (uint32_t)val.size();
    m.last_access= now_ns();
    m.access_cnt = 1;
    if (was_new) ndram_.fetch_add(1);
    m.tier = Tier::DRAM;
    return true;
}

bool TierEngine::get(std::string_view key, std::string* out) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = index_.find(std::string(key));
    if (it == index_.end()) return false;
    it->second.last_access = now_ns();
    it->second.access_cnt++;
    if (out) out->assign(it->second.size, '\0');
    return true;
}

bool TierEngine::erase(std::string_view key) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = index_.find(std::string(key));
    if (it == index_.end()) return false;
    switch (it->second.tier) {
        case Tier::DRAM: ndram_.fetch_sub(1); break;
        case Tier::NVME: nnvme_.fetch_sub(1); break;
        case Tier::HDD:  nhdd_.fetch_sub(1);  break;
    }
    index_.erase(it);
    return true;
}

void TierEngine::put_meta(std::string_view key, uint64_t offset, uint32_t size) {
    std::lock_guard<std::mutex> lk(mu_);
    auto& m = index_[std::string(key)];
    // A key is new only when we've never seen it before (access_cnt==0).
    bool was_new = (m.access_cnt == 0);
    m.offset      = offset;
    m.size        = size;
    m.tier        = Tier::DRAM;
    m.last_access = now_ns();
    m.access_cnt  = m.access_cnt + 1;
    m.dram_slot_free = false;
    m.dram_offset = offset;
    if (was_new) ndram_.fetch_add(1);
}

bool TierEngine::get_meta(std::string_view key, uint64_t* offset, uint32_t* size) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = index_.find(std::string(key));
    if (it == index_.end()) return false;
    if (offset) *offset = it->second.offset;
    if (size)   *size   = it->second.size;
    it->second.last_access = now_ns();
    it->second.access_cnt++;
    return true;
}

bool TierEngine::get_meta_full(std::string_view key, ObjectMeta* out) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = index_.find(std::string(key));
    if (it == index_.end()) return false;
    if (out) *out = it->second;
    return true;
}

void TierEngine::on_access(std::string_view key) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = index_.find(std::string(key));
    if (it == index_.end()) return;
    it->second.last_access = now_ns();
    it->second.access_cnt++;
}

namespace {

void push_event(std::mutex& mu, std::vector<MigrationEvent>& events,
                MigrationEvent ev) {
    std::lock_guard<std::mutex> lk(mu);
    events.push_back(std::move(ev));
    if (events.size() > 64) events.erase(events.begin(),
        events.begin() + (events.size() - 64));
}

} // namespace

bool TierEngine::demote(std::string_view key, Tier to,
                        const void* slab_base, size_t slab_len) {
    if (!io_) return false;
    std::string skey(key);
    ObjectMeta snap{};
    {
        std::lock_guard<std::mutex> lk(mu_);
        auto it = index_.find(skey);
        if (it == index_.end()) return false;
        if (it->second.tier == to) return false;
        snap = it->second;
    }
    if (snap.size == 0 || snap.size > slab_len) return false;

    // Read source bytes:
    // - DRAM source: memcpy from slab_base + snap.offset
    // - NVMe source: sync_read from FG file
    std::vector<char> tmp(snap.size);
    if (snap.tier == Tier::DRAM) {
        std::memcpy(tmp.data(), (const char*)slab_base + snap.offset, snap.size);
    } else if (snap.tier == Tier::NVME) {
        int r = io_->sync_read(IoScheduler::Prio::FG, tmp.data(),
                               snap.size, snap.offset);
        if (r < 0 || (size_t)r != snap.size) return false;
    } else {
        // HDD -> anything: read from BG first.
        int r = io_->sync_read(IoScheduler::Prio::BG, tmp.data(),
                               snap.size, snap.offset);
        if (r < 0 || (size_t)r != snap.size) return false;
    }

    // Target tier: bump-pointer allocate offset, then write.
    uint64_t target_off = 0;
    IoScheduler::Prio prio =
        (to == Tier::NVME) ? IoScheduler::Prio::FG : IoScheduler::Prio::BG;
    if (to == Tier::NVME) {
        target_off = nvme_next_off_.fetch_add(cfg_.tier_slot_size);
    } else if (to == Tier::HDD) {
        target_off = hdd_next_off_.fetch_add(cfg_.tier_slot_size);
    } else {
        return false;
    }
    int w = io_->sync_write(prio, tmp.data(), snap.size, target_off);
    if (w < 0 || (size_t)w != snap.size) return false;

    // Commit index.
    {
        std::lock_guard<std::mutex> lk(mu_);
        auto it = index_.find(skey);
        if (it == index_.end()) return false;
        Tier from = it->second.tier;
        if (from == Tier::DRAM && !it->second.dram_slot_free) {
            // dram_offset keeps where the DRAM slot was, so main.cpp can free it.
            it->second.dram_offset    = it->second.offset;
            it->second.dram_slot_free = true;
        }
        it->second.tier   = to;
        it->second.offset = target_off;

        // Stats update.
        if (from == Tier::DRAM) ndram_.fetch_sub(1);
        else if (from == Tier::NVME) nnvme_.fetch_sub(1);
        else if (from == Tier::HDD)  nhdd_.fetch_sub(1);
        if (to == Tier::NVME)      nnvme_.fetch_add(1);
        else if (to == Tier::HDD)  nhdd_.fetch_add(1);
        else if (to == Tier::DRAM) ndram_.fetch_add(1);

        push_event(events_mu_, events_,
                   MigrationEvent{now_ns(), skey, from, to, snap.size});
    }
    return true;
}

bool TierEngine::promote(std::string_view key, void* dram_slot,
                         uint64_t dram_offset) {
    if (!io_ || !dram_slot) return false;
    std::string skey(key);
    ObjectMeta snap{};
    {
        std::lock_guard<std::mutex> lk(mu_);
        auto it = index_.find(skey);
        if (it == index_.end()) return false;
        if (it->second.tier == Tier::DRAM) return false;
        snap = it->second;
    }
    IoScheduler::Prio prio =
        (snap.tier == Tier::NVME) ? IoScheduler::Prio::FG : IoScheduler::Prio::BG;
    int r = io_->sync_read(prio, dram_slot, snap.size, snap.offset);
    if (r < 0 || (size_t)r != snap.size) return false;

    {
        std::lock_guard<std::mutex> lk(mu_);
        auto it = index_.find(skey);
        if (it == index_.end()) return false;
        Tier from = it->second.tier;
        it->second.tier   = Tier::DRAM;
        it->second.offset = dram_offset;
        it->second.dram_offset    = dram_offset;
        it->second.dram_slot_free = false;
        it->second.last_access = now_ns();

        if (from == Tier::NVME) nnvme_.fetch_sub(1);
        else if (from == Tier::HDD) nhdd_.fetch_sub(1);
        ndram_.fetch_add(1);

        push_event(events_mu_, events_,
                   MigrationEvent{now_ns(), skey, from, Tier::DRAM, snap.size});
    }
    return true;
}

void TierEngine::tick_migration() {
    // Scan is invoked periodically by the tier_migrator thread in main.cpp.
    // The real work happens there (it has access to slab_base for DRAM reads),
    // so this hook stays intentionally lightweight.
}

std::vector<MigrationEvent> TierEngine::recent_events() const {
    std::lock_guard<std::mutex> lk(events_mu_);
    return events_;
}

uint64_t TierEngine::count(Tier t) const {
    switch (t) {
        case Tier::DRAM: return ndram_.load();
        case Tier::NVME: return nnvme_.load();
        case Tier::HDD:  return nhdd_.load();
    }
    return 0;
}

} // namespace nr
