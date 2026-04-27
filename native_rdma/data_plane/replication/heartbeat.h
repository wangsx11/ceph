#pragma once
#include <atomic>
#include <thread>
#include <string>
#include <functional>
#include <cstdint>

namespace nr {

class Heartbeat {
public:
    using OnLost     = std::function<void(const std::string& peer_id)>;
    using OnRecovery = std::function<void(const std::string& peer_id)>;
    using OnSend     = std::function<void()>;  // invoked every interval_ms

    bool start(const std::string& peer_id, int interval_ms, int timeout_ms);
    void stop();
    void tick(const std::string& peer_id);   // called on incoming HB
    void set_on_lost(OnLost cb)        { on_lost_ = std::move(cb); }
    void set_on_recover(OnRecovery cb) { on_rec_ = std::move(cb); }
    void set_on_send(OnSend cb)        { on_send_ = std::move(cb); }
    bool peer_alive() const            { return peer_alive_.load(); }

private:
    std::atomic<bool>  running_{false};
    std::thread        th_;
    int                interval_ms_ = 1000;
    int                timeout_ms_  = 3000;
    std::atomic<uint64_t> last_hb_ms_{0};
    std::atomic<bool>  peer_alive_{false};
    std::string        peer_id_;
    OnLost             on_lost_;
    OnRecovery         on_rec_;
    OnSend             on_send_;
};

} // namespace nr
