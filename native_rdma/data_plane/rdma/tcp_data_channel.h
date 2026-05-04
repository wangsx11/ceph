#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <string>
#include <thread>

namespace nr {

// Small TCP data-plane channel used to validate and exercise the traditional
// TCP/IP transport path independently from the RDMA WRITE replication path.
class TcpDataChannel {
public:
    struct Config {
        std::string self_ip;
        std::string peer_ip;
        uint16_t port = 18516;
        int timeout_ms = 2000;
    };

    using PutHandler = std::function<bool(const std::string& key,
                                          const std::string& value,
                                          std::string* err)>;
    using GetHandler = std::function<bool(const std::string& key,
                                          std::string* value)>;

    TcpDataChannel() = default;
    ~TcpDataChannel();

    bool start(const Config& cfg, PutHandler put_handler, GetHandler get_handler);
    void stop();

    bool put_peer(const std::string& key, const std::string& value,
                  std::string* err = nullptr);
    bool get_peer(const std::string& key, std::string* value,
                  std::string* err = nullptr);

    bool running() const { return running_.load(); }
    uint64_t puts_received() const { return puts_received_.load(); }
    uint64_t gets_received() const { return gets_received_.load(); }

private:
    bool connect_peer(int* fd, std::string* err);
    void server_loop();
    void handle_client(int fd);

    Config cfg_;
    PutHandler put_handler_;
    GetHandler get_handler_;
    std::atomic<bool> running_{false};
    std::atomic<bool> stop_{false};
    std::atomic<uint64_t> puts_received_{0};
    std::atomic<uint64_t> gets_received_{0};
    std::thread server_thread_;
    int listen_fd_ = -1;
};

} // namespace nr
