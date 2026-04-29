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
    uint32_t size         = 0;   // user bytes (<= slot_size) - original (uncompressed)
    Tier     tier         = Tier::DRAM;
    uint64_t last_access  = 0;
    uint32_t access_cnt   = 0;
    uint8_t  flags        = 0;
    uint64_t fingerprint  = 0;
    // When tier != DRAM, offset points into the NVMe/HDD backing file
    // and `dram_slot_free` signals the DRAM slot has been returned to Slab.
    bool     dram_slot_free = false;
    uint64_t dram_offset  = 0;   // original DRAM slab offset (for rollback/promote)
    // W4 M1-4: compression info (only meaningful on HDD tier for now).
    uint32_t compressed_size = 0;  // bytes actually written on disk (<=size)
    uint8_t  algo         = 0;     // 0=none, 1=zstd, 2=lz4
    // -------- Heat-score tiering (M6 v2) --------
    // Exponentially-decaying access score inspired by m6_tiering.py's
    // calculate_heat_score().  Algorithm (O(1) per access, zero extra
    // memory per access):
    //     on_access(now):
    //         dt = (now - score_ts) / 1e9         // seconds
    //         heat_score = heat_score * exp(-alpha*dt) + score_init
    //         score_ts   = now
    // On migrator scan we only need the time-decayed "view" without the
    // +score_init term (see calc_heat_score()).
    double   heat_score   = 0.0;   // current decayed activity score
    uint64_t score_ts     = 0;     // last time heat_score was updated (ns)
    uint64_t birth_ns     = 0;     // object first seen (for grace window)
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
        // ---- Heat-score thresholds (M6 v2) ----
        // Objects are demoted when their decayed score falls below these
        // cutoffs; promotion back UP the hierarchy is driven by actual
        // reads (handled in main.cpp's GET path via TierEngine::promote)
        // and does NOT need a threshold here.
        double      demote_hot_score  = 0.30;  // DRAM < 0.30 -> NVMe
        double      demote_warm_score = 0.05;  // NVMe < 0.05 -> HDD
        double      time_decay_alpha  = 0.10;  // per-second decay rate
        double      heat_score_init   = 1.0;   // score bump per access
        uint64_t    score_grace_ns    = 2ULL * 1000 * 1000 * 1000; // 2s protection
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

    // W5 fast-path: fuse get_meta + put_meta into a single critical section.
    // If `key` already exists, `*existing_off` is set to the slot's offset so
    // the caller can overwrite in place and we return false (no new slot).
    // If `key` is new, the caller's `new_off`/`new_size` are committed as the
    // new DRAM meta and we return true (so caller knows to account for a
    // fresh slab allocation). This halves lock acquisitions on the PUT
    // hot path compared to the old get_meta -> slab.alloc -> put_meta
    // sequence, which was the bottleneck that kept 16-thread PUT ~600k ops/s.
    bool reserve_or_reuse_slot(std::string_view key,
                               uint64_t* existing_off, uint32_t* existing_size,
                               uint64_t  new_off,      uint32_t  new_size);

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

    // ---- Heat score (M6 v2) ----
    // Read-only query: decays the stored score to `now` (ns) but does NOT
    // mutate the object. Used by the tier migrator to pick demote targets.
    double calc_heat_score(const ObjectMeta& m, uint64_t now_ns) const;
    // Access callback used by put/get paths: decays the score then
    // adds `heat_score_init`, updates `score_ts`, and bumps `last_access`.
    // Caller must hold `mu_`.
    void   bump_score_locked(ObjectMeta& m, uint64_t now_ns);

    // ---- W4 migration primitives (used by tick_migration) ----
    // Migrate `key` from its current tier to `to` tier. Needs slab_base to
    // read data from DRAM when demoting.
    bool demote(std::string_view key, Tier to,
                const void* slab_base, size_t slab_len);
    // Bring `key` back to DRAM. Caller supplies a free slot address+offset.
    bool promote(std::string_view key, void* dram_slot, uint64_t dram_offset);

    // Recent migration events (bounded ring, latest 64).
    std::vector<MigrationEvent> recent_events() const;

    // W4 M1-4: compression stats (HDD-layer only in current impl).
    struct CompressStats {
        uint64_t raw_bytes   = 0;   // total original bytes sent to compression
        uint64_t cmp_bytes   = 0;   // total compressed bytes stored
        uint64_t n_compressed = 0;  // count of objects compressed
    };
    CompressStats compress_stats() const;

    // Drop the in-memory index and return the list of DRAM slab offsets that
    // were in use, so the caller can free them back to the SlabPool.
    // Also resets all tier counters, migration events, compression stats and
    // NVMe/HDD bump-pointer offsets. Intended for admin/demo flush only.
    std::vector<uint64_t> reset_all();

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

    // Compression accounting (W4 M1-4). Only bumped by HDD demotes.
    std::atomic<uint64_t> cmp_raw_bytes_{0};
    std::atomic<uint64_t> cmp_cmp_bytes_{0};
    std::atomic<uint64_t> cmp_n_{0};
};

} // namespace nr
