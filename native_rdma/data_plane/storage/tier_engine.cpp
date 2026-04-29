#include "tier_engine.h"
#include "io_scheduler.h"
#include "compress.h"
#include "../common/logger.h"
#include "../common/time_util.h"

#include <algorithm>
#include <cstring>
#include <string>

namespace nr {

bool TierEngine::init(const Config& cfg) {
    cfg_ = cfg;
    NR_INFO("TierEngine init: nvme=%s hdd=%s dram_cap=%zuMB "
            "nvme_cap=%zuMB hdd_cap=%zuMB demote_idle=%llu/%llu ns",
            cfg.nvme_path.c_str(), cfg.hdd_path.c_str(),
            cfg.dram_cap_bytes / (1024ULL * 1024),
            cfg.nvme_cap_bytes / (1024ULL * 1024),
            cfg.hdd_cap_bytes  / (1024ULL * 1024),
            (unsigned long long)cfg.dram_demote_idle_ns,
            (unsigned long long)cfg.nvme_demote_idle_ns);
    return true;
}

void TierEngine::shutdown() {}

bool TierEngine::put(std::string_view key, std::string_view val, uint8_t /*prio*/) {
    std::lock_guard<std::mutex> lk(mu_);
    auto& m = index_[std::string(key)];
    bool was_new = (m.size == 0);
    m.size       = (uint32_t)val.size();
    m.last_access= now_ns();
    m.access_cnt = 1;
    if (was_new) ndram_.fetch_add(1);
    m.tier = Tier::DRAM;
    return true;
}

bool TierEngine::get(std::string_view key, std::string* out) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = index_.find(std::string(key));
    if (it == index_.end()) return false;
    it->second.last_access = now_ns();
    it->second.access_cnt++;
    if (out) out->assign(it->second.size, '\0');
    return true;
}

bool TierEngine::erase(std::string_view key) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = index_.find(std::string(key));
    if (it == index_.end()) return false;
    switch (it->second.tier) {
        case Tier::DRAM: ndram_.fetch_sub(1); break;
        case Tier::NVME: nnvme_.fetch_sub(1); break;
        case Tier::HDD:  nhdd_.fetch_sub(1);  break;
    }
    index_.erase(it);
    return true;
}

void TierEngine::put_meta(std::string_view key, uint64_t offset, uint32_t size) {
    std::lock_guard<std::mutex> lk(mu_);
    auto& m = index_[std::string(key)];
    // A key is new only when we've never seen it before (access_cnt==0).
    bool was_new = (m.access_cnt == 0);
    Tier prev_tier = m.tier;
    m.offset      = offset;
    m.size        = size;
    m.tier        = Tier::DRAM;
    m.last_access = now_ns();
    m.access_cnt  = m.access_cnt + 1;
    m.dram_slot_free = false;
    m.dram_offset = offset;
    if (was_new) {
        ndram_.fetch_add(1);
    } else if (prev_tier != Tier::DRAM) {
        // Existing key, but it lived in a lower tier (e.g. was demoted to
        // NVMe/HDD and now overwritten with a fresh PUT that re-lands in
        // DRAM). Fix tier counters so later demote() does not underflow.
        if      (prev_tier == Tier::NVME) nnvme_.fetch_sub(1);
        else if (prev_tier == Tier::HDD)  nhdd_.fetch_sub(1);
        ndram_.fetch_add(1);
    }
}

bool TierEngine::reserve_or_reuse_slot(std::string_view key,
                                       uint64_t* existing_off,
                                       uint32_t* existing_size,
                                       uint64_t  new_off,
                                       uint32_t  new_size) {
    // Fast-path: fuse "check existing" + "commit new DRAM meta" into a
    // single critical section.  Returns true when the key is brand new
    // (caller accounted for a fresh slab slot at `new_off`); returns false
    // when the key already existed (caller should NOT call slab.alloc, and
    // `*existing_off/*existing_size` reflect the in-place target).
    std::lock_guard<std::mutex> lk(mu_);
    auto it = index_.find(std::string(key));
    if (it != index_.end()) {
        // Key exists. Report its current slot and just bump counters.
        if (existing_off)  *existing_off  = it->second.offset;
        if (existing_size) *existing_size = it->second.size;
        ObjectMeta& m = it->second;
        Tier prev_tier = m.tier;
        // Overwrite-in-place semantics: the caller will memcpy into the
        // existing slot (DRAM). Only update tier counters when the key was
        // previously demoted; DRAM->DRAM stays on DRAM.
        m.offset      = m.offset;          // unchanged
        m.size        = new_size;          // new payload length
        m.tier        = Tier::DRAM;
        m.last_access = now_ns();
        m.access_cnt++;
        m.dram_slot_free = false;
        m.dram_offset = m.offset;
        if (prev_tier != Tier::DRAM) {
            if      (prev_tier == Tier::NVME) nnvme_.fetch_sub(1);
            else if (prev_tier == Tier::HDD)  nhdd_.fetch_sub(1);
            ndram_.fetch_add(1);
        }
        return false;
    }
    // Key is new. Commit the provided slot as its meta.
    ObjectMeta& m = index_[std::string(key)];
    m.offset      = new_off;
    m.size        = new_size;
    m.tier        = Tier::DRAM;
    m.last_access = now_ns();
    m.access_cnt  = 1;
    m.dram_slot_free = false;
    m.dram_offset = new_off;
    ndram_.fetch_add(1);
    return true;
}

bool TierEngine::get_meta(std::string_view key, uint64_t* offset, uint32_t* size) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = index_.find(std::string(key));
    if (it == index_.end()) return false;
    if (offset) *offset = it->second.offset;
    if (size)   *size   = it->second.size;
    it->second.last_access = now_ns();
    it->second.access_cnt++;
    return true;
}

bool TierEngine::get_meta_full(std::string_view key, ObjectMeta* out) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = index_.find(std::string(key));
    if (it == index_.end()) return false;
    if (out) *out = it->second;
    return true;
}

void TierEngine::on_access(std::string_view key) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = index_.find(std::string(key));
    if (it == index_.end()) return;
    it->second.last_access = now_ns();
    it->second.access_cnt++;
}

namespace {

void push_event(std::mutex& mu, std::vector<MigrationEvent>& events,
                MigrationEvent ev) {
    std::lock_guard<std::mutex> lk(mu);
    events.push_back(std::move(ev));
    if (events.size() > 64) events.erase(events.begin(),
        events.begin() + (events.size() - 64));
}

} // namespace

bool TierEngine::demote(std::string_view key, Tier to,
                        const void* slab_base, size_t slab_len) {
    if (!io_) return false;
    std::string skey(key);
    ObjectMeta snap{};
    {
        std::lock_guard<std::mutex> lk(mu_);
        auto it = index_.find(skey);
        if (it == index_.end()) return false;
        if (it->second.tier == to) return false;
        snap = it->second;
    }
    if (snap.size == 0 || snap.size > slab_len) return false;

    // Read source bytes:
    // - DRAM source: memcpy from slab_base + snap.offset
    // - NVMe source: sync_read from FG file (plaintext)
    // - HDD source : sync_read compressed_size bytes then decompress
    std::vector<char> tmp(snap.size);
    if (snap.tier == Tier::DRAM) {
        std::memcpy(tmp.data(), (const char*)slab_base + snap.offset, snap.size);
    } else if (snap.tier == Tier::NVME) {
        int r = io_->sync_read(IoScheduler::Prio::FG, tmp.data(),
                               snap.size, snap.offset);
        if (r < 0 || (size_t)r != snap.size) {
            NR_WARN("demote read NVMe failed key=%s off=%lu sz=%u r=%d",
                    skey.c_str(), (unsigned long)snap.offset, snap.size, r);
            return false;
        }
    } else {
        // HDD source: read compressed_size bytes then decompress.
        uint32_t on_disk = snap.compressed_size ? snap.compressed_size : snap.size;
        std::string enc(on_disk, '\0');
        int r = io_->sync_read(IoScheduler::Prio::BG, enc.data(),
                               on_disk, snap.offset);
        if (r < 0 || (size_t)r != on_disk) return false;
        if (snap.algo != 0) {
            std::string dec;
            if (!CompressEngine::decompress(
                    snap.algo == 1 ? CompressAlgo::ZSTD : CompressAlgo::LZ4,
                    enc, &dec) || dec.size() != snap.size) {
                NR_WARN("HDD decompress failed key=%s", skey.c_str());
                return false;
            }
            std::memcpy(tmp.data(), dec.data(), snap.size);
        } else {
            std::memcpy(tmp.data(), enc.data(), snap.size);
        }
    }

    // Target tier: bump-pointer allocate offset, then write.
    // HDD writes go through CompressEngine to save space (cold path ok to pay CPU).
    uint64_t target_off = 0;
    IoScheduler::Prio prio =
        (to == Tier::NVME) ? IoScheduler::Prio::FG : IoScheduler::Prio::BG;
    uint32_t on_disk_size = snap.size;
    uint8_t  chosen_algo  = 0;
    std::string enc_buf;
    const char* write_ptr = tmp.data();
    if (to == Tier::HDD) {
        CompressAlgo algo = CompressEngine::pick(snap.size);
        if (algo != CompressAlgo::NONE) {
            std::string raw(tmp.data(), snap.size);
            if (CompressEngine::compress(algo, raw, &enc_buf)
                && enc_buf.size() < snap.size /* only commit if it helped */) {
                on_disk_size = (uint32_t)enc_buf.size();
                chosen_algo  = (algo == CompressAlgo::ZSTD) ? 1 : 2;
                write_ptr    = enc_buf.data();
                cmp_raw_bytes_.fetch_add(snap.size);
                cmp_cmp_bytes_.fetch_add(on_disk_size);
                cmp_n_.fetch_add(1);
            }
        }
        // HDD slot stride large enough to fit on-disk size rounded up.
        size_t stride = cfg_.tier_slot_size;
        while (stride < on_disk_size) stride *= 2;
        target_off = hdd_next_off_.fetch_add(stride);
    } else if (to == Tier::NVME) {
        target_off = nvme_next_off_.fetch_add(cfg_.tier_slot_size);
    } else {
        return false;
    }
    int w = io_->sync_write(prio, write_ptr, on_disk_size, target_off);
    if (w < 0 || (size_t)w != on_disk_size) {
        NR_WARN("demote write %s failed key=%s off=%lu sz=%u w=%d",
                to == Tier::HDD ? "HDD" : "NVMe",
                skey.c_str(), (unsigned long)target_off, on_disk_size, w);
        return false;
    }

    // Commit index.
    {
        std::lock_guard<std::mutex> lk(mu_);
        auto it = index_.find(skey);
        if (it == index_.end()) return false;
        Tier from = it->second.tier;
        if (from == Tier::DRAM && !it->second.dram_slot_free) {
            // dram_offset keeps where the DRAM slot was, so main.cpp can free it.
            it->second.dram_offset    = it->second.offset;
            it->second.dram_slot_free = true;
        }
        it->second.tier    = to;
        it->second.offset  = target_off;
        it->second.compressed_size = (to == Tier::HDD) ? on_disk_size : 0;
        it->second.algo    = (to == Tier::HDD) ? chosen_algo : 0;

        // Stats update (saturating sub: never underflow uint64 to 2^64-1).
        auto safe_sub = [&](std::atomic<uint64_t>& ctr) {
            uint64_t cur = ctr.load(std::memory_order_relaxed);
            while (cur > 0) {
                if (ctr.compare_exchange_weak(cur, cur - 1,
                        std::memory_order_relaxed)) return;
            }
            // cur == 0: accounting mismatch, keep at 0 and log once.
            NR_WARN("tier counter underflow avoided (key=%s)", skey.c_str());
        };
        if      (from == Tier::DRAM) safe_sub(ndram_);
        else if (from == Tier::NVME) safe_sub(nnvme_);
        else if (from == Tier::HDD)  safe_sub(nhdd_);
        if      (to == Tier::NVME)   nnvme_.fetch_add(1);
        else if (to == Tier::HDD)    nhdd_.fetch_add(1);
        else if (to == Tier::DRAM)   ndram_.fetch_add(1);

        push_event(events_mu_, events_,
                   MigrationEvent{now_ns(), skey, from, to, snap.size});
    }
    return true;
}

bool TierEngine::promote(std::string_view key, void* dram_slot,
                         uint64_t dram_offset) {
    if (!io_ || !dram_slot) return false;
    std::string skey(key);
    ObjectMeta snap{};
    {
        std::lock_guard<std::mutex> lk(mu_);
        auto it = index_.find(skey);
        if (it == index_.end()) return false;
        if (it->second.tier == Tier::DRAM) return false;
        snap = it->second;
    }
    IoScheduler::Prio prio =
        (snap.tier == Tier::NVME) ? IoScheduler::Prio::FG : IoScheduler::Prio::BG;
    if (snap.tier == Tier::HDD && snap.algo != 0) {
        // Read compressed bytes then decompress into the dram slot.
        uint32_t on_disk = snap.compressed_size ? snap.compressed_size : snap.size;
        std::string enc(on_disk, '\0');
        int r = io_->sync_read(prio, enc.data(), on_disk, snap.offset);
        if (r < 0 || (size_t)r != on_disk) return false;
        std::string dec;
        if (!CompressEngine::decompress(
                snap.algo == 1 ? CompressAlgo::ZSTD : CompressAlgo::LZ4,
                enc, &dec) || dec.size() != snap.size) {
            NR_WARN("promote HDD decompress failed key=%s", skey.c_str());
            return false;
        }
        std::memcpy(dram_slot, dec.data(), snap.size);
    } else {
        int r = io_->sync_read(prio, dram_slot, snap.size, snap.offset);
        if (r < 0 || (size_t)r != snap.size) return false;
    }

    {
        std::lock_guard<std::mutex> lk(mu_);
        auto it = index_.find(skey);
        if (it == index_.end()) return false;
        Tier from = it->second.tier;
        it->second.tier   = Tier::DRAM;
        it->second.offset = dram_offset;
        it->second.dram_offset    = dram_offset;
        it->second.dram_slot_free = false;
        it->second.last_access = now_ns();

        if (from == Tier::NVME) {
            uint64_t cur = nnvme_.load(std::memory_order_relaxed);
            while (cur > 0 && !nnvme_.compare_exchange_weak(cur, cur - 1,
                        std::memory_order_relaxed)) {}
        } else if (from == Tier::HDD) {
            uint64_t cur = nhdd_.load(std::memory_order_relaxed);
            while (cur > 0 && !nhdd_.compare_exchange_weak(cur, cur - 1,
                        std::memory_order_relaxed)) {}
        }
        ndram_.fetch_add(1);

        push_event(events_mu_, events_,
                   MigrationEvent{now_ns(), skey, from, Tier::DRAM, snap.size});
    }
    return true;
}

void TierEngine::tick_migration() {
    // Scan is invoked periodically by the tier_migrator thread in main.cpp.
    // The real work happens there (it has access to slab_base for DRAM reads),
    // so this hook stays intentionally lightweight.
}

std::vector<MigrationEvent> TierEngine::recent_events() const {
    std::lock_guard<std::mutex> lk(events_mu_);
    return events_;
}

TierEngine::CompressStats TierEngine::compress_stats() const {
    CompressStats s;
    s.raw_bytes    = cmp_raw_bytes_.load();
    s.cmp_bytes    = cmp_cmp_bytes_.load();
    s.n_compressed = cmp_n_.load();
    return s;
}

std::vector<uint64_t> TierEngine::reset_all() {
    std::vector<uint64_t> dram_offs;
    {
        std::lock_guard<std::mutex> lk(mu_);
        dram_offs.reserve(index_.size());
        for (auto& kv : index_) {
            const ObjectMeta& m = kv.second;
            // We only need to free slots whose DRAM slot is still attributed
            // to this key. When `dram_slot_free == true` the slot has already
            // been returned to the slab by an earlier demote()/main.cpp path,
            // so caller must NOT free it again.
            if (m.tier == Tier::DRAM || !m.dram_slot_free) {
                // Use offset when still in DRAM, dram_offset as fallback.
                uint64_t off = (m.tier == Tier::DRAM) ? m.offset : m.dram_offset;
                dram_offs.push_back(off);
            }
        }
        index_.clear();
    }
    ndram_.store(0);
    nnvme_.store(0);
    nhdd_.store(0);
    nvme_next_off_.store(0);
    hdd_next_off_.store(0);
    cmp_raw_bytes_.store(0);
    cmp_cmp_bytes_.store(0);
    cmp_n_.store(0);
    {
        std::lock_guard<std::mutex> lk(events_mu_);
        events_.clear();
    }
    return dram_offs;
}

uint64_t TierEngine::count(Tier t) const {
    // For the M6 tiered-storage demo we MUST report numbers that match the
    // ground-truth tier field stored in `index_`.  Relying solely on the
    // atomic counters (ndram_/nnvme_/nhdd_) is fragile because every code
    // path that mutates ObjectMeta::tier must remember to adjust them in
    // lock-step; any single missed update shows up in the UI as "NVMe→HDD
    // said OK but hdd stays 0".  To keep demo output trustworthy, we
    // recompute by scanning index_.  The scan is O(N) under the index
    // mutex — fine for demo scale (N_OBJS = 1000) and it is only hit by
    // RPC_TIER_STATS (low-frequency UI polling), not by the data path.
    std::lock_guard<std::mutex> lk(mu_);
    uint64_t n = 0;
    for (auto& kv : index_) {
        if (kv.second.tier == t) ++n;
    }
    return n;
}

} // namespace nr
