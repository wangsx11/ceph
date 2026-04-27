#pragma once
#include <cstdint>
#include <string>
#include <unordered_map>
#include <mutex>

namespace nr {

struct PoolInfo {
    uint32_t    pool_id    = 0;
    std::string name;
    uint64_t    base_addr  = 0;   // local pointer as uint64
    size_t      length     = 0;
    uint32_t    rkey       = 0;
    uint32_t    lkey       = 0;
    uint32_t    tenant_id  = 0;
    int         numa       = -1;
};

// Namespace-level registry for pools; also stores remote peer's pool info
// after handshake so that ObjectRouter can locate remote addresses.
class PoolRegistry {
public:
    static PoolRegistry& instance() {
        static PoolRegistry r;
        return r;
    }

    uint32_t register_local(const PoolInfo& info);
    bool     register_remote(const std::string& peer_id, const PoolInfo& info);

    bool     find_local(const std::string& name, PoolInfo* out) const;
    bool     find_remote(const std::string& peer_id, const std::string& name,
                         PoolInfo* out) const;

private:
    mutable std::mutex mu_;
    std::unordered_map<std::string, PoolInfo> local_;
    // peer_id -> (name -> info)
    std::unordered_map<std::string,
        std::unordered_map<std::string, PoolInfo>> remote_;
    uint32_t next_id_ = 1;
};

} // namespace nr
