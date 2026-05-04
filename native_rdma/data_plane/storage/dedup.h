#pragma once
#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>
#include <mutex>

namespace nr {

// Content-defined dedup registry: fingerprint -> refcount.
class Dedup {
public:
    struct Entry {
        uint64_t offset = 0;
        uint32_t raw_size = 0;
        uint32_t stored_size = 0;
        uint8_t  algo = 0;
        uint32_t refs = 0;
    };
    struct Stats {
        uint64_t unique_objects = 0;
        uint64_t duplicate_objects = 0;
        uint64_t saved_bytes = 0;
        uint64_t logical_bytes = 0;
    };

    static uint64_t fingerprint(std::string_view data);

    // Returns fingerprint (first 8 bytes of SHA-256) and whether duplicate.
    uint64_t observe(const std::string& data, bool* duplicate = nullptr);
    bool lookup(uint64_t fingerprint, Entry* out) const;
    bool retain_or_insert(uint64_t fingerprint, uint64_t offset,
                          uint32_t raw_size, uint32_t stored_size,
                          uint8_t algo, Entry* out,
                          bool* duplicate = nullptr);
    void     release(uint64_t fingerprint);
    Stats    stats() const;
    void     reset();

private:
    mutable std::mutex mu_;
    std::unordered_map<uint64_t, Entry> refs_;
    uint64_t duplicate_objects_ = 0;
    uint64_t saved_bytes_ = 0;
    uint64_t logical_bytes_ = 0;
};

} // namespace nr
