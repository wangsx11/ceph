#include "uds_server.h"
#include "../common/logger.h"

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <cstring>
#include <cstdint>

namespace nr {

static int read_n(int fd, void* buf, size_t n) {
    char* p = (char*)buf;
    while (n) {
        ssize_t r = ::read(fd, p, n);
        if (r <= 0) return -1;
        p += r; n -= r;
    }
    return 0;
}
static int write_n(int fd, const void* buf, size_t n) {
    const char* p = (const char*)buf;
    while (n) {
        ssize_t r = ::write(fd, p, n);
        if (r <= 0) return -1;
        p += r; n -= r;
    }
    return 0;
}

bool UdsServer::start(const std::string& socket_path) {
    path_ = socket_path;
    ::unlink(path_.c_str());
    lfd_ = ::socket(AF_UNIX, SOCK_STREAM, 0);
    if (lfd_ < 0) return false;
    sockaddr_un a{}; a.sun_family = AF_UNIX;
    std::strncpy(a.sun_path, path_.c_str(), sizeof(a.sun_path) - 1);
    if (::bind(lfd_, (sockaddr*)&a, sizeof(a)) < 0) { ::close(lfd_); return false; }
    if (::listen(lfd_, 8) < 0) { ::close(lfd_); return false; }
    running_.store(true);
    th_ = std::thread(&UdsServer::run, this);
    NR_INFO("UdsServer listening on %s", path_.c_str());
    return true;
}

void UdsServer::stop() {
    if (!running_.exchange(false)) return;
    if (lfd_ >= 0) { ::shutdown(lfd_, SHUT_RDWR); ::close(lfd_); lfd_ = -1; }
    if (th_.joinable()) th_.join();
    ::unlink(path_.c_str());
}

void UdsServer::run() {
    while (running_.load(std::memory_order_relaxed)) {
        int fd = ::accept(lfd_, nullptr, nullptr);
        if (fd < 0) { if (running_.load()) continue; else break; }
        // Increase socket buffers for large batch frames
        int bufsz = 4 * 1024 * 1024;
        setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &bufsz, sizeof(bufsz));
        setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &bufsz, sizeof(bufsz));
        std::thread([this, fd]() { handle_client(fd); }).detach();
    }
}

// Frame format: [u32 kind_len][kind][u32 body_len][body] -> response [u32 resp_len][resp]
void UdsServer::handle_client(int fd) {
    while (running_.load(std::memory_order_relaxed)) {
        uint32_t kl = 0;
        if (read_n(fd, &kl, 4) < 0) break;
        std::string kind(kl, '\0');
        if (kl && read_n(fd, &kind[0], kl) < 0) break;
        uint32_t bl = 0;
        if (read_n(fd, &bl, 4) < 0) break;
        std::string body(bl, '\0');
        if (bl && read_n(fd, &body[0], bl) < 0) break;
        std::string resp;
        if (handler_) handler_(kind, body, &resp);
        uint32_t rl = (uint32_t)resp.size();
        if (write_n(fd, &rl, 4) < 0) break;
        if (rl && write_n(fd, resp.data(), rl) < 0) break;
    }
    ::close(fd);
}

} // namespace nr
