// native_rdma bench client: hits the data-plane UDS directly with RPC_KV_PUT/GET
// to measure end-to-end hot-path throughput & latency without going through HTTP.
//
// Usage:
//   ./bin/nr_bench --uds=/tmp/native_rdma-dp.sock --op=put --threads=8 --duration=10 --val-size=64
//
// Reports:  ops/s, avg(us), p50(us), p99(us), p999(us), max(us)

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <vector>
#include <algorithm>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>

struct Opt {
    std::string uds      = "/tmp/native_rdma-dp.sock";
    std::string op       = "put";      // put | get | mix
    int         threads  = 8;
    int         duration = 10;         // seconds
    int         val_size = 64;
    int         keyspace = 10000;      // rotating key id range
};

static void parse(int argc, char** argv, Opt& o) {
    for (int i = 1; i < argc; ++i) {
        std::string s = argv[i];
        auto eq = s.find('=');
        std::string k = s.substr(0, eq);
        std::string v = eq == std::string::npos ? "" : s.substr(eq + 1);
        if      (k == "--uds")      o.uds = v;
        else if (k == "--op")       o.op = v;
        else if (k == "--threads")  o.threads = std::stoi(v);
        else if (k == "--duration") o.duration = std::stoi(v);
        else if (k == "--val-size") o.val_size = std::stoi(v);
        else if (k == "--keyspace") o.keyspace = std::stoi(v);
    }
}

static int uds_connect(const std::string& path) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    sockaddr_un a{}; a.sun_family = AF_UNIX;
    std::strncpy(a.sun_path, path.c_str(), sizeof(a.sun_path) - 1);
    if (connect(fd, (sockaddr*)&a, sizeof(a)) < 0) { close(fd); return -1; }
    return fd;
}

static int write_all(int fd, const void* buf, size_t n) {
    const char* p = (const char*)buf;
    while (n) {
        ssize_t r = write(fd, p, n);
        if (r <= 0) return -1;
        p += r; n -= r;
    }
    return 0;
}
static int read_all(int fd, void* buf, size_t n) {
    char* p = (char*)buf;
    while (n) {
        ssize_t r = read(fd, p, n);
        if (r <= 0) return -1;
        p += r; n -= r;
    }
    return 0;
}

// Wire: [u32 kind_len][kind][u32 body_len][body] -> [u32 resp_len][resp]
static bool rpc_call(int fd, const char* kind, const void* body, size_t blen) {
    uint32_t kl = (uint32_t)std::strlen(kind);
    if (write_all(fd, &kl, 4) < 0) return false;
    if (write_all(fd, kind, kl) < 0) return false;
    uint32_t bl = (uint32_t)blen;
    if (write_all(fd, &bl, 4) < 0) return false;
    if (bl && write_all(fd, body, bl) < 0) return false;
    uint32_t rl = 0;
    if (read_all(fd, &rl, 4) < 0) return false;
    // Drain and discard response body.
    std::vector<char> buf(rl);
    if (rl && read_all(fd, buf.data(), rl) < 0) return false;
    return true;
}

static inline uint64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

int main(int argc, char** argv) {
    Opt o; parse(argc, argv, o);
    std::printf("[nr_bench] uds=%s op=%s threads=%d duration=%ds "
                "val_size=%d keyspace=%d\n",
                o.uds.c_str(), o.op.c_str(), o.threads, o.duration,
                o.val_size, o.keyspace);

    std::atomic<bool> stop{false};
    std::atomic<uint64_t> ops_done{0};
    std::atomic<uint64_t> ops_fail{0};
    std::vector<std::vector<uint32_t>> lats(o.threads); // per-thread ns samples

    // Pre-generate a value buffer.
    std::string val(o.val_size, 'X');

    auto worker = [&](int tid) {
        int fd = uds_connect(o.uds);
        if (fd < 0) { std::printf("[t%d] uds connect failed\n", tid); return; }
        lats[tid].reserve(2'000'000);
        uint64_t local_cnt = 0;
        char keybuf[64];
        std::vector<char> body;
        body.reserve(64 + o.val_size);
        while (!stop.load(std::memory_order_relaxed)) {
            int key_id = (int)((tid * 1000003ULL + local_cnt) % (uint64_t)o.keyspace);
            int kn = std::snprintf(keybuf, sizeof(keybuf), "bk_%d_%d", tid, key_id);
            body.clear();
            body.insert(body.end(), keybuf, keybuf + kn);

            const char* kind = "RPC_KV_PUT";
            if (o.op == "get") {
                kind = "RPC_KV_GET";
                // body: just the key
            } else {
                // PUT body: key \0 val
                body.push_back('\0');
                body.insert(body.end(), val.begin(), val.end());
            }
            if (o.op == "mix") {
                // 80% PUT / 20% GET
                if ((local_cnt & 7) < 6) {
                    kind = "RPC_KV_PUT";
                    body.push_back('\0');
                    body.insert(body.end(), val.begin(), val.end());
                } else {
                    kind = "RPC_KV_GET";
                }
            }

            uint64_t t0 = now_ns();
            bool ok = rpc_call(fd, kind, body.data(), body.size());
            uint64_t dt = now_ns() - t0;
            if (ok) {
                ops_done.fetch_add(1, std::memory_order_relaxed);
                if (dt < 0xFFFFFFFFu) lats[tid].push_back((uint32_t)dt);
            } else {
                ops_fail.fetch_add(1, std::memory_order_relaxed);
                // Reconnect on error.
                close(fd); fd = uds_connect(o.uds);
                if (fd < 0) break;
            }
            ++local_cnt;
        }
        close(fd);
    };

    uint64_t t_start = now_ns();
    std::vector<std::thread> ths;
    for (int i = 0; i < o.threads; ++i) ths.emplace_back(worker, i);
    std::this_thread::sleep_for(std::chrono::seconds(o.duration));
    stop.store(true);
    for (auto& t : ths) t.join();
    double elapsed = (now_ns() - t_start) / 1e9;

    // Aggregate per-thread histograms.
    std::vector<uint32_t> all;
    size_t total_samples = 0;
    for (auto& v : lats) total_samples += v.size();
    all.reserve(total_samples);
    for (auto& v : lats) all.insert(all.end(), v.begin(), v.end());
    uint64_t ops = ops_done.load();
    uint64_t fail = ops_fail.load();

    double avg_us = 0, p50 = 0, p99 = 0, p999 = 0, pmax = 0;
    if (!all.empty()) {
        uint64_t sum = 0;
        for (auto v : all) sum += v;
        avg_us = (double)sum / all.size() / 1000.0;
        std::sort(all.begin(), all.end());
        auto at = [&](double q)->double {
            size_t i = (size_t)(all.size() * q);
            if (i >= all.size()) i = all.size() - 1;
            return all[i] / 1000.0;
        };
        p50  = at(0.50);
        p99  = at(0.99);
        p999 = at(0.999);
        pmax = all.back() / 1000.0;
    }

    std::printf("\n==== nr_bench result ====\n");
    std::printf("  elapsed       : %.2f s\n", elapsed);
    std::printf("  threads       : %d\n",     o.threads);
    std::printf("  op            : %s\n",     o.op.c_str());
    std::printf("  ops ok/fail   : %lu / %lu\n",
                (unsigned long)ops, (unsigned long)fail);
    std::printf("  ops/s         : %.0f\n",   ops / elapsed);
    std::printf("  latency us    : avg=%.2f  p50=%.2f  p99=%.2f  p99.9=%.2f  max=%.2f\n",
                avg_us, p50, p99, p999, pmax);
    return 0;
}
