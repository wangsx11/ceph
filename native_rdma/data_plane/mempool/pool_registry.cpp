#include "pool_registry.h"

namespace nr {

uint32_t PoolRegistry::register_local(const PoolInfo& info_in) {
    std::lock_guard<std::mutex> lk(mu_);
    PoolInfo info = info_in;
    if (info.pool_id == 0) info.pool_id = next_id_++;
    local_[info.name] = info;
    return info.pool_id;
}

bool PoolRegistry::register_remote(const std::string& peer_id,
                                   const PoolInfo& info) {
    std::lock_guard<std::mutex> lk(mu_);
    remote_[peer_id][info.name] = info;
    return true;
}

bool PoolRegistry::find_local(const std::string& name, PoolInfo* out) const {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = local_.find(name);
    if (it == local_.end()) return false;
    if (out) *out = it->second;
    return true;
}

bool PoolRegistry::find_remote(const std::string& peer_id,
                               const std::string& name, PoolInfo* out) const {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = remote_.find(peer_id);
    if (it == remote_.end()) return false;
    auto jt = it->second.find(name);
    if (jt == it->second.end()) return false;
    if (out) *out = jt->second;
    return true;
}

} // namespace nr
