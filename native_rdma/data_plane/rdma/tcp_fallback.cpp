#include "tcp_fallback.h"
#include "../common/logger.h"
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>
#include <cstring>

namespace nr {

static void set_tcp_no_delay(int fd) {
    int v = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &v, sizeof(v));
}

bool TcpFallback::listen(const std::string& ip, uint16_t port) {
    int lfd = socket(AF_INET, SOCK_STREAM, 0);
    if (lfd < 0) return false;
    int yes = 1;
    setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
    sockaddr_in a{}; a.sin_family = AF_INET; a.sin_port = htons(port);
    inet_pton(AF_INET, ip.c_str(), &a.sin_addr);
    if (bind(lfd, (sockaddr*)&a, sizeof(a)) < 0) { ::close(lfd); return false; }
    if (::listen(lfd, 1) < 0) { ::close(lfd); return false; }
    NR_INFO("TcpFallback listen on %s:%u", ip.c_str(), port);
    fd_ = accept(lfd, nullptr, nullptr);
    ::close(lfd);
    if (fd_ < 0) return false;
    set_tcp_no_delay(fd_);
    return true;
}

bool TcpFallback::connect(const std::string& peer_ip, uint16_t port) {
    fd_ = socket(AF_INET, SOCK_STREAM, 0);
    if (fd_ < 0) return false;
    sockaddr_in a{}; a.sin_family = AF_INET; a.sin_port = htons(port);
    inet_pton(AF_INET, peer_ip.c_str(), &a.sin_addr);
    if (::connect(fd_, (sockaddr*)&a, sizeof(a)) < 0) {
        ::close(fd_); fd_ = -1; return false;
    }
    set_tcp_no_delay(fd_);
    NR_INFO("TcpFallback connected to %s:%u", peer_ip.c_str(), port);
    return true;
}

int TcpFallback::send_all(const void* buf, size_t len) {
    const char* p = static_cast<const char*>(buf);
    size_t left = len;
    while (left) {
        ssize_t n = send(fd_, p, left, 0);
        if (n <= 0) return -1;
        p += n; left -= n;
    }
    return (int)len;
}

int TcpFallback::recv_all(void* buf, size_t len) {
    char* p = static_cast<char*>(buf);
    size_t left = len;
    while (left) {
        ssize_t n = recv(fd_, p, left, 0);
        if (n <= 0) return -1;
        p += n; left -= n;
    }
    return (int)len;
}

void TcpFallback::close() {
    if (fd_ >= 0) { ::close(fd_); fd_ = -1; }
}

} // namespace nr
