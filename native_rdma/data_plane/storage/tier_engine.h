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
    uint64_t offset       = 0;
    uint32_t size         = 0;
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

    bool put(std::string_view key, std::string_view val, uint8_t prio);
    bool get(std::string_view key, std::string* out);
    bool erase(std::string_view key);

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
