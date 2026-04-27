#pragma once
#include "rdma_core.h"
#include <string>
#include <functional>

namespace nr {

// Thin wrapper around librdmacm for establishing the control QP.
// For the hot-path data QPs we still use raw verbs + out-of-band info exchange
// over this control channel.
class CmHandler {
public:
    using OnEstablished = std::function<void(const PeerEndpoint&)>;

    bool listen(const std::string& ip, uint16_t port);
    bool connect(const std::string& peer_ip, uint16_t port,
                 const PeerEndpoint& local, PeerEndpoint* remote_out);

    void set_on_established(OnEstablished cb) { on_est_ = std::move(cb); }

private:
    OnEstablished on_est_;
};

} // namespace nr
