#include "tier_engine.h"
#include "../common/logger.h"
#include "../common/time_util.h"

namespace nr {

bool TierEngine::init(const Config& cfg) {
    cfg_ = cfg;
    NR_INFO("TierEngine init: nvme=%s hdd=%s dram_cap=%zuMB",
            cfg.nvme_path.c_str(), cfg.hdd_path.c_str(),
            cfg.dram_cap_bytes / (1024ULL * 1024));
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
    // TODO: actually copy into DRAM slab / persist to NVMe WAL.
    return true;
}

bool TierEngine::get(std::string_view key, std::string* out) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = index_.find(std::string(key));
    if (it == index_.end()) return false;
    it->second.last_access = now_ns();
    it->second.access_cnt++;
    if (out) out->assign(it->second.size, '\0');  // TODO real read
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

void TierEngine::on_access(std::string_view key) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = index_.find(std::string(key));
    if (it == index_.end()) return;
    it->second.last_access = now_ns();
    it->second.access_cnt++;
}

void TierEngine::tick_migration() {
    // TODO: scan index_, apply DRAM↔NVME↔HDD migration rules described in
    // docs/自研方案.md §3.6.3. Left as TODO skeleton.
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
