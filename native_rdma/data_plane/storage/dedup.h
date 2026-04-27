#pragma once
#include <cstdint>
#include <string>
#include <unordered_map>
#include <mutex>

namespace nr {

// Content-defined dedup registry: fingerprint -> refcount.
class Dedup {
public:
    // Returns fingerprint (first 8 bytes of SHA-256) and whether duplicate.
    uint64_t observe(const std::string& data, bool* duplicate = nullptr);
    void     release(uint64_t fingerprint);

private:
    std::mutex mu_;
    std::unordered_map<uint64_t, uint32_t> refs_;
};

} // namespace nr
