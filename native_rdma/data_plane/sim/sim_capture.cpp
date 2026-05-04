#include "sim_capture.h"
#include "../common/logger.h"
#include "../common/time_util.h"

#include <chrono>
#include <cstring>
#include <filesystem>

namespace nr {

SimCapture& SimCapture::instance() {
    static SimCapture i;
    return i;
}

bool SimCapture::init(const Config& cfg) {
    std::lock_guard<std::mutex> lk(mu_);
    // Fast-path: stop any existing session first.
    if (running_.load()) {
        // Caller must stop() before reconfiguring.
        return false;
    }
    cfg_ = cfg;
    ring_.clear();
    ring_.reserve(cfg_.ring_bytes);
    drain_.clear();
    drain_.reserve(cfg_.ring_bytes);
    s_ = Stats{};

    // Prepare WAL path; create the directory if missing.
    std::error_code ec;
    std::filesystem::create_directories(cfg_.capture_dir, ec);
    log_path_ = cfg_.capture_dir + "/sim_" + cfg_.tag + ".log";
    {
        std::lock_guard<std::mutex> log_lk(log_mu_);
        log_.close();
        log_.open(log_path_, std::ios::binary | std::ios::app);
    }
    if (!log_) {
        NR_ERROR("SimCapture: cannot open WAL %s", log_path_.c_str());
        return false;
    }
    NR_INFO("SimCapture ready: dir=%s tag=%s ring=%zuB flush=%dms",
            cfg_.capture_dir.c_str(), cfg_.tag.c_str(),
            cfg_.ring_bytes, cfg_.flush_interval_ms);
    return true;
}

bool SimCapture::start() {
    if (running_.exchange(true)) return true;   // already running
    bg_ = std::thread(&SimCapture::run, this);
    return true;
}

void SimCapture::stop() {
    if (!running_.exchange(false)) return;
    if (bg_.joinable()) bg_.join();
    // Final drain, in case the last batch hadn't been flushed yet.
    {
        std::lock_guard<std::mutex> lk(mu_);
        std::swap(ring_, drain_);
    }
    if (!drain_.empty()) {
        write_sink(drain_.data(), drain_.size());
        std::lock_guard<std::mutex> lk(mu_);
        s_.flushed_events += (s_.pushed_events - s_.flushed_events);
        s_.flushed_bytes  += drain_.size();
        drain_.clear();
    }
    {
        std::lock_guard<std::mutex> log_lk(log_mu_);
        if (log_.is_open()) log_.flush();
    }
}

void SimCapture::reset() {
    std::lock_guard<std::mutex> lk(mu_);
    ring_.clear();
    drain_.clear();
    s_ = Stats{};
    std::lock_guard<std::mutex> log_lk(log_mu_);
    log_.close();
    // Truncate the WAL: reopen without append.
    log_.open(log_path_, std::ios::binary | std::ios::trunc);
}

bool SimCapture::push_attr(uint64_t entity_id,
                           const void* blob, size_t blob_len) {
    return push_raw(TYPE_OBJECT_ATTR, entity_id, 0, blob, blob_len);
}

bool SimCapture::push_event(uint64_t a_id, uint64_t b_id,
                            const void* blob, size_t blob_len) {
    return push_raw(TYPE_INTERACTION, a_id, b_id, blob, blob_len);
}

bool SimCapture::push_raw(uint16_t type, uint64_t entity_id,
                          uint64_t peer_id,
                          const void* blob, size_t blob_len) {
    // blob_len must fit in uint16_t (64 KB per event is plenty for sim).
    if (blob_len > 0xFFFFu) return false;

    SimEventHeader hdr{};
    hdr.ts_ns     = nr::now_ns();
    hdr.entity_id = entity_id;
    hdr.peer_id   = peer_id;
    hdr.type      = type;
    hdr.blob_len  = (uint16_t)blob_len;

    const size_t total = sizeof(hdr) + blob_len;
    std::lock_guard<std::mutex> lk(mu_);
    if (ring_.size() + total > cfg_.ring_bytes) {
        // Backpressure: don't grow past the configured bound. Caller can
        // retry after a flush interval, or accept the drop.
        s_.dropped_events++;
        return false;
    }
    const size_t pos = ring_.size();
    ring_.resize(pos + total);
    std::memcpy(&ring_[pos], &hdr, sizeof(hdr));
    if (blob_len) std::memcpy(&ring_[pos + sizeof(hdr)], blob, blob_len);
    s_.pushed_events++;
    s_.pushed_bytes += total;
    if (type == TYPE_OBJECT_ATTR) s_.object_attr_events++;
    else if (type == TYPE_INTERACTION) s_.interaction_events++;
    return true;
}

SimCapture::Stats SimCapture::stats() const {
    std::lock_guard<std::mutex> lk(mu_);
    Stats s = s_;
    s.wal_path = log_path_;
    std::error_code ec;
    if (!log_path_.empty() && std::filesystem::exists(log_path_, ec)) {
        s.wal_bytes = std::filesystem::file_size(log_path_, ec);
    }
    return s;
}

void SimCapture::run() {
    while (running_.load(std::memory_order_relaxed)) {
        std::this_thread::sleep_for(
            std::chrono::milliseconds(cfg_.flush_interval_ms));
        // Swap ring for a fresh drain buffer -- producers are only
        // blocked for the duration of the swap.
        size_t n_bytes = 0;
        uint64_t n_evts = 0;
        {
            std::lock_guard<std::mutex> lk(mu_);
            if (ring_.empty()) continue;
            std::swap(ring_, drain_);
            n_bytes = drain_.size();
            // Each event is at least sizeof(SimEventHeader); we count
            // events precisely in push_raw but that's under mu_ so we
            // snapshot the delta of pushed_events vs flushed_events as
            // the event count for this batch.
            n_evts = s_.pushed_events - s_.flushed_events;
        }
        write_sink(drain_.data(), drain_.size());
        {
            std::lock_guard<std::mutex> lk(mu_);
            s_.flushed_events += n_evts;
            s_.flushed_bytes  += n_bytes;
        }
        drain_.clear();
    }
}

bool SimCapture::write_sink(const void* buf, size_t len) {
    std::lock_guard<std::mutex> log_lk(log_mu_);
    if (!log_.is_open() || len == 0) return true;
    log_.write(reinterpret_cast<const char*>(buf), (std::streamsize)len);
    // Make the WAL immediately visible to stats/tests. fsync_on_flush still
    // controls durability beyond the process and OS page cache.
    log_.flush();
    return (bool)log_;
}

} // namespace nr
