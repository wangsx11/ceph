#pragma once
#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>
#include <mutex>
#include <atomic>
#include <vector>

namespace nr {

class IoScheduler;

enum class Tier : uint8_t { DRAM = 0, NVME = 1, HDD = 2 };

struct ObjectMeta {
    uint64_t offset       = 0;   // offset into the local slab (bytes) OR tier file offset
    uint32_t size         = 0;   // user bytes (<= slot_size)
    Tier     tier         = Tier::DRAM;
    uint64_t last_access  = 0;
    uint32_t access_cnt   = 0;
    uint8_t  flags        = 0;
    uint64_t fingerprint  = 0;
    // When tier != DRAM, offset points into the NVMe/HDD backing file
    // and `dram_slot_free` signals the DRAM slot has been returned to Slab.
    bool     dram_slot_free = false;
    uint64_t dram_offset  = 0;   // original DRAM slab offset (for rollback/promote)
};

struct MigrationEvent {
    uint64_t    ts_ns;
    std::string key;
    Tier        from;
    Tier        to;
    uint64_t    bytes;
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
        // Heat thresholds.
        uint64_t    dram_demote_idle_ns = 10ULL * 1000 * 1000 * 1000; // 10s idle -> NVMe
        uint64_t    nvme_demote_idle_ns = 30ULL * 1000 * 1000 * 1000; // 30s idle -> HDD
        // NVMe/HDD tier slot sizing (fixed 1KB for simplicity in demo).
        size_t      tier_slot_size = 1024;
        size_t      nvme_max_objects = 1ULL * 1024 * 1024; // 1M slots
        size_t      hdd_max_objects  = 4ULL * 1024 * 1024; // 4M slots
    };

    bool init(const Config& cfg);
    void shutdown();

    // Attach an IoScheduler (NVMe=FG, HDD=BG). Call after IoScheduler::init.
    void set_io_scheduler(IoScheduler* io) { io_ = io; }

    // Legacy stub (kept for callers that don't use slab-backed storage).
    bool put(std::string_view key, std::string_view val, uint8_t prio);
    bool get(std::string_view key, std::string* out);
    bool erase(std::string_view key);

    // ---- W2: slab-backed API ----
    // Record that `key` now lives at slab `offset` with `size` bytes.
    void put_meta(std::string_view key, uint64_t offset, uint32_t size);
    bool get_meta(std::string_view key, uint64_t* offset, uint32_t* size);
    // Full meta copy (for callers that need tier info too).
    bool get_meta_full(std::string_view key, ObjectMeta* out);

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

    // ---- W4 migration primitives (used by tick_migration) ----
    // Migrate `key` from its current tier to `to` tier. Needs slab_base to
    // read data from DRAM when demoting.
    bool demote(std::string_view key, Tier to,
                const void* slab_base, size_t slab_len);
    // Bring `key` back to DRAM. Caller supplies a free slot address+offset.
    bool promote(std::string_view key, void* dram_slot, uint64_t dram_offset);

    // Recent migration events (bounded ring, latest 64).
    std::vector<MigrationEvent> recent_events() const;

    // Stats
    uint64_t count(Tier t) const;

private:
    Config     cfg_;
    mutable std::mutex mu_;
    std::unordered_map<std::string, ObjectMeta> index_;
    std::atomic<uint64_t> ndram_{0}, nnvme_{0}, nhdd_{0};

    // Tier backing files are managed through IoScheduler; here we only
    // track the bump-pointer offsets for fresh writes.
    IoScheduler* io_ = nullptr;
    std::atomic<uint64_t> nvme_next_off_{0};
    std::atomic<uint64_t> hdd_next_off_{0};

    mutable std::mutex events_mu_;
    std::vector<MigrationEvent> events_;   // bounded, oldest-first
};

} // namespace nr
