#pragma once
#include <cstddef>
#include <cstdint>
#include <string>

namespace nr {

// Minimal TCP fallback for environments where RDMA is unavailable.
// Used when `--no-rdma` is passed or CmHandler::connect fails.
class TcpFallback {
public:
    bool listen(const std::string& ip, uint16_t port);
    bool connect(const std::string& peer_ip, uint16_t port);

    int  send_all(const void* buf, size_t len);
    int  recv_all(void* buf, size_t len);

    void close();

private:
    int fd_ = -1;
};

} // namespace nr
