#pragma once
#include <cstdint>
#include <string>
#include <unordered_set>
#include <mutex>

namespace nr {

// Lightweight tenant isolation: ACL + per-tenant pool tagging.
// RDMA-level isolation is enforced by giving each tenant its own PD+MR.
class Isolation {
public:
    static Isolation& instance() { static Isolation i; return i; }

    void allow(uint32_t tenant_id, const std::string& pool_name);
    bool check(uint32_t tenant_id, const std::string& pool_name) const;

private:
    mutable std::mutex mu_;
    // (tenant_id << 32 | hash(name)) style set, for simplicity use string key.
    std::unordered_set<std::string> acl_;
    static std::string key(uint32_t t, const std::string& n);
};

} // namespace nr
