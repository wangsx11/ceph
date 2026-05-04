#include "tcp_data_channel.h"
#include "../common/logger.h"

#include <arpa/inet.h>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>
#include <vector>

namespace nr {
namespace {

static constexpr uint32_t kMagic = 0x3143544e; // "NTC1" little-endian.
static constexpr uint16_t kOpPut = 1;
static constexpr uint16_t kOpGet = 2;
static constexpr uint16_t kOpResp = 100;
static constexpr uint32_t kMaxKey = 4096;
static constexpr uint32_t kMaxValue = 16 * 1024 * 1024;

struct FrameHeader {
    uint32_t magic;
    uint16_t op;
    uint16_t status;
    uint32_t key_len;
    uint32_t value_len;
};

static void set_socket_opts(int fd, int timeout_ms) {
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    timeval tv{};
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
}

static bool send_all(int fd, const void* data, size_t len) {
    const char* p = static_cast<const char*>(data);
    while (len > 0) {
        ssize_t n = ::send(fd, p, len, 0);
        if (n <= 0) return false;
        p += n;
        len -= (size_t)n;
    }
    return true;
}

static bool recv_all(int fd, void* data, size_t len) {
    char* p = static_cast<char*>(data);
    while (len > 0) {
        ssize_t n = ::recv(fd, p, len, 0);
        if (n <= 0) return false;
        p += n;
        len -= (size_t)n;
    }
    return true;
}

static bool send_frame(int fd, uint16_t op, uint16_t status,
                       const std::string& key, const std::string& value) {
    FrameHeader h{};
    h.magic = kMagic;
    h.op = op;
    h.status = status;
    h.key_len = (uint32_t)key.size();
    h.value_len = (uint32_t)value.size();
    if (!send_all(fd, &h, sizeof(h))) return false;
    if (!key.empty() && !send_all(fd, key.data(), key.size())) return false;
    if (!value.empty() && !send_all(fd, value.data(), value.size())) return false;
    return true;
}

static bool recv_frame(int fd, FrameHeader* h, std::string* key,
                       std::string* value) {
    if (!recv_all(fd, h, sizeof(*h))) return false;
    if (h->magic != kMagic) return false;
    if (h->key_len > kMaxKey || h->value_len > kMaxValue) return false;
    key->assign(h->key_len, '\0');
    value->assign(h->value_len, '\0');
    if (h->key_len && !recv_all(fd, key->data(), h->key_len)) return false;
    if (h->value_len && !recv_all(fd, value->data(), h->value_len)) return false;
    return true;
}

} // namespace

TcpDataChannel::~TcpDataChannel() {
    stop();
}

bool TcpDataChannel::start(const Config& cfg, PutHandler put_handler,
                           GetHandler get_handler) {
    cfg_ = cfg;
    put_handler_ = std::move(put_handler);
    get_handler_ = std::move(get_handler);
    stop_.store(false);

    listen_fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
    if (listen_fd_ < 0) {
        NR_ERROR("TcpDataChannel socket failed errno=%d", errno);
        return false;
    }
    int yes = 1;
    setsockopt(listen_fd_, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
    set_socket_opts(listen_fd_, cfg_.timeout_ms);

    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(cfg_.port);
    if (inet_pton(AF_INET, cfg_.self_ip.c_str(), &a.sin_addr) != 1) {
        a.sin_addr.s_addr = htonl(INADDR_ANY);
    }
    if (::bind(listen_fd_, (sockaddr*)&a, sizeof(a)) != 0) {
        NR_WARN("TcpDataChannel bind %s:%u failed errno=%d, retry 0.0.0.0",
                cfg_.self_ip.c_str(), cfg_.port, errno);
        a.sin_addr.s_addr = htonl(INADDR_ANY);
        if (::bind(listen_fd_, (sockaddr*)&a, sizeof(a)) != 0) {
            NR_ERROR("TcpDataChannel bind failed errno=%d", errno);
            ::close(listen_fd_);
            listen_fd_ = -1;
            return false;
        }
    }
    if (::listen(listen_fd_, 64) != 0) {
        NR_ERROR("TcpDataChannel listen failed errno=%d", errno);
        ::close(listen_fd_);
        listen_fd_ = -1;
        return false;
    }
    running_.store(true);
    server_thread_ = std::thread(&TcpDataChannel::server_loop, this);
    NR_INFO("TcpDataChannel listen on %s:%u peer=%s timeout_ms=%d",
            cfg_.self_ip.c_str(), cfg_.port, cfg_.peer_ip.c_str(), cfg_.timeout_ms);
    return true;
}

void TcpDataChannel::stop() {
    stop_.store(true);
    running_.store(false);
    if (listen_fd_ >= 0) {
        ::shutdown(listen_fd_, SHUT_RDWR);
        ::close(listen_fd_);
        listen_fd_ = -1;
    }
    if (server_thread_.joinable()) server_thread_.join();
}

bool TcpDataChannel::connect_peer(int* fd, std::string* err) {
    *fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (*fd < 0) {
        if (err) *err = "socket failed";
        return false;
    }
    set_socket_opts(*fd, cfg_.timeout_ms);
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(cfg_.port);
    if (inet_pton(AF_INET, cfg_.peer_ip.c_str(), &a.sin_addr) != 1) {
        if (err) *err = "bad peer ip";
        ::close(*fd);
        *fd = -1;
        return false;
    }
    if (::connect(*fd, (sockaddr*)&a, sizeof(a)) != 0) {
        if (err) *err = std::string("connect failed errno=") + std::to_string(errno);
        ::close(*fd);
        *fd = -1;
        return false;
    }
    return true;
}

bool TcpDataChannel::put_peer(const std::string& key, const std::string& value,
                              std::string* err) {
    int fd = -1;
    if (!connect_peer(&fd, err)) return false;
    bool ok = send_frame(fd, kOpPut, 0, key, value);
    FrameHeader h{};
    std::string resp_key, resp_value;
    if (ok) ok = recv_frame(fd, &h, &resp_key, &resp_value);
    ::close(fd);
    if (!ok || h.op != kOpResp || h.status != 1) {
        if (err) *err = resp_value.empty() ? "tcp put response failed" : resp_value;
        return false;
    }
    return true;
}

bool TcpDataChannel::get_peer(const std::string& key, std::string* value,
                              std::string* err) {
    int fd = -1;
    if (!connect_peer(&fd, err)) return false;
    bool ok = send_frame(fd, kOpGet, 0, key, "");
    FrameHeader h{};
    std::string resp_key, resp_value;
    if (ok) ok = recv_frame(fd, &h, &resp_key, &resp_value);
    ::close(fd);
    if (!ok || h.op != kOpResp || h.status != 1) {
        if (err) *err = resp_value.empty() ? "tcp get response failed" : resp_value;
        return false;
    }
    *value = std::move(resp_value);
    return true;
}

void TcpDataChannel::server_loop() {
    while (!stop_.load()) {
        int fd = ::accept(listen_fd_, nullptr, nullptr);
        if (fd < 0) {
            if (!stop_.load()) std::this_thread::sleep_for(std::chrono::milliseconds(20));
            continue;
        }
        set_socket_opts(fd, cfg_.timeout_ms);
        handle_client(fd);
        ::close(fd);
    }
}

void TcpDataChannel::handle_client(int fd) {
    FrameHeader h{};
    std::string key, value;
    if (!recv_frame(fd, &h, &key, &value)) {
        (void)send_frame(fd, kOpResp, 0, "", "bad frame");
        return;
    }
    if (h.op == kOpPut) {
        std::string err;
        bool ok = put_handler_ ? put_handler_(key, value, &err) : false;
        if (ok) {
            puts_received_.fetch_add(1, std::memory_order_relaxed);
            (void)send_frame(fd, kOpResp, 1, "", "ok");
        } else {
            (void)send_frame(fd, kOpResp, 0, "", err.empty() ? "put handler failed" : err);
        }
    } else if (h.op == kOpGet) {
        std::string out;
        bool ok = get_handler_ ? get_handler_(key, &out) : false;
        if (ok) {
            gets_received_.fetch_add(1, std::memory_order_relaxed);
            (void)send_frame(fd, kOpResp, 1, "", out);
        } else {
            (void)send_frame(fd, kOpResp, 0, "", "not found");
        }
    } else {
        (void)send_frame(fd, kOpResp, 0, "", "unknown op");
    }
}

} // namespace nr
