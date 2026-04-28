#pragma once
#include <cstdint>
#include <string>
#include <unordered_set>
#include <mutex>
#include <vector>

namespace nr {

// Lightweight tenant isolation: ACL + per-tenant pool tagging.
// RDMA-level isolation is enforced by giving each tenant its own PD+MR.
class Isolation {
public:
    static Isolation& instance() { static Isolation i; return i; }

    // Add a (tenant_id, pool_name) pair to the allow list.
    void allow(uint32_t tenant_id, const std::string& pool_name);
    // Remove the entry; no-op if it wasn't present.
    void deny (uint32_t tenant_id, const std::string& pool_name);
    // Returns true when the pair is currently whitelisted.
    bool check(uint32_t tenant_id, const std::string& pool_name) const;
    // Snapshot of every "(tenant_id, pool_name)" string currently allowed.
    // Used by RPC_ISO_LIST to surface ACL state to the demo/control plane.
    std::vector<std::string> list_allowed() const;

private:
    mutable std::mutex mu_;
    // (tenant_id << 32 | hash(name)) style set, for simplicity use string key.
    std::unordered_set<std::string> acl_;
    static std::string key(uint32_t t, const std::string& n);
};

} // namespace nr
