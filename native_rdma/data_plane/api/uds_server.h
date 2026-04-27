#pragma once
#include <string>
#include <atomic>
#include <thread>
#include <functional>

namespace nr {

// Unix Domain Socket RPC server. Uses a simple length-prefixed framing with
// protobuf `RpcEnvelope` payloads. The handler is invoked on the server thread.
class UdsServer {
public:
    using Handler = std::function<void(const std::string& kind,
                                       const std::string& body,
                                       std::string* resp)>;

    bool  start(const std::string& socket_path);
    void  stop();
    void  set_handler(Handler h) { handler_ = std::move(h); }

private:
    void run();
    void handle_client(int fd);

    std::string       path_;
    int               lfd_ = -1;
    std::atomic<bool> running_{false};
    std::thread       th_;
    Handler           handler_;
};

} // namespace nr
