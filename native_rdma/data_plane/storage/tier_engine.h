#pragma once
#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>
#include <mutex>
#include <atomic>

namespace nr {

enum class Tier : uint8_t { DRAM = 0, NVME = 1, HDD = 2 };

struct ObjectMeta {
    uint64_t offset       = 0;   // offset into the local slab (bytes)
    uint32_t size         = 0;   // user bytes (<= slot_size)
    Tier     tier         = Tier::DRAM;
    uint64_t last_access  = 0;
    uint32_t access_cnt   = 0;
    uint8_t  flags        = 0;
    uint64_t fingerprint  = 0;
};

class TierEngine {
public:
    struct Config {
        std::string nvme_path = "/dev/shm/native_rdma_warm";
        std::string hdd_path  = "/dev/shm/native_rdma_cold";
        size_t      dram_cap_bytes = 8ULL  * 1024 * 1024 * 1024;
        size_t      nvme_cap_bytes = 64ULL * 1024 * 1024 * 1024;
        size_t      hdd_cap_bytes  = 512ULL* 1024 * 1024 * 1024;
        int         migrate_interval_ms = 1000;
    };

    bool init(const Config& cfg);
    void shutdown();

    // Legacy stub (kept for callers that don't use slab-backed storage).
    bool put(std::string_view key, std::string_view val, uint8_t prio);
    bool get(std::string_view key, std::string* out);
    bool erase(std::string_view key);

    // ---- W2: slab-backed API ----
    // Record that `key` now lives at slab `offset` with `size` bytes.
    void put_meta(std::string_view key, uint64_t offset, uint32_t size);
    bool get_meta(std::string_view key, uint64_t* offset, uint32_t* size);

    // Iterate for snapshot. Callback(key, meta) returns false to stop.
    template <class Fn>
    void for_each(Fn&& fn) const {
        std::lock_guard<std::mutex> lk(mu_);
        for (auto& kv : index_) {
            if (!fn(kv.first, kv.second)) break;
        }
    }

    void on_access(std::string_view key);
    void tick_migration();   // called by tier_migrator thread

    // Stats
    uint64_t count(Tier t) const;

private:
    Config     cfg_;
    mutable std::mutex mu_;
    std::unordered_map<std::string, ObjectMeta> index_;
    std::atomic<uint64_t> ndram_{0}, nnvme_{0}, nhdd_{0};
};

} // namespace nr
