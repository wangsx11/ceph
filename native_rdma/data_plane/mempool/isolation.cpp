#include "isolation.h"

namespace nr {

std::string Isolation::key(uint32_t t, const std::string& n) {
    return std::to_string(t) + "|" + n;
}

void Isolation::allow(uint32_t tenant_id, const std::string& pool_name) {
    std::lock_guard<std::mutex> lk(mu_);
    acl_.insert(key(tenant_id, pool_name));
}

void Isolation::deny(uint32_t tenant_id, const std::string& pool_name) {
    std::lock_guard<std::mutex> lk(mu_);
    acl_.erase(key(tenant_id, pool_name));
}

bool Isolation::check(uint32_t tenant_id, const std::string& pool_name) const {
    std::lock_guard<std::mutex> lk(mu_);
    return acl_.find(key(tenant_id, pool_name)) != acl_.end();
}

std::vector<std::string> Isolation::list_allowed() const {
    std::lock_guard<std::mutex> lk(mu_);
    std::vector<std::string> out;
    out.reserve(acl_.size());
    for (const auto& s : acl_) out.push_back(s);
    return out;
}

} // namespace nr
