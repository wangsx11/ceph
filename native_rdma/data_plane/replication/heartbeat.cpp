#include "heartbeat.h"
#include "../common/time_util.h"
#include "../common/logger.h"
#include <chrono>

namespace nr {

bool Heartbeat::start(const std::string& peer_id, int interval_ms, int timeout_ms) {
    peer_id_     = peer_id;
    interval_ms_ = interval_ms;
    timeout_ms_  = timeout_ms;
    // Start in "lost" state until we actually receive a heartbeat.
    peer_alive_.store(false);
    last_hb_ms_.store(0);
    running_.store(true);
    th_ = std::thread([this]() {
        while (running_.load(std::memory_order_relaxed)) {
            // 1) try to send our heartbeat (non-fatal if peer not ready yet).
            if (on_send_) on_send_();

            // 2) evaluate peer liveness.
            uint64_t t    = now_ms();
            uint64_t last = last_hb_ms_.load();
            if (last == 0) {
                // never received a HB yet: keep LOST silently.
            } else if (peer_alive_.load() && t - last > (uint64_t)timeout_ms_) {
                peer_alive_.store(false);
                NR_WARN("peer %s LOST (last hb %lums ago)",
                        peer_id_.c_str(), (unsigned long)(t - last));
                if (on_lost_) on_lost_(peer_id_);
            } else if (!peer_alive_.load() && t - last <= (uint64_t)timeout_ms_) {
                peer_alive_.store(true);
                NR_INFO("peer %s RECOVERED", peer_id_.c_str());
                if (on_rec_) on_rec_(peer_id_);
            }

            std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms_));
        }
    });
    return true;
}

void Heartbeat::stop() {
    if (!running_.exchange(false)) return;
    if (th_.joinable()) th_.join();
}

void Heartbeat::tick(const std::string&) {
    last_hb_ms_.store(now_ms());
}

} // namespace nr
