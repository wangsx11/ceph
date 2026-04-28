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
    std::string prio     = "";         // "hi" | "lo" | "" (default)
    // Default key layout is per-thread ("bk_<tid>_<id>") so independent
    // threads don't step on each other -- useful for measuring per-thread
    // latency (perf_02) or QoS isolation (perf_03).
    //
    // For bandwidth tests (perf_06) we want a *shared* keyspace: the PUT
    // phase writes keyspace=N unique keys, then the GET phase reads the
    // same N keys regardless of thread count. Otherwise 16-thread warmup
    // would create 16*N keys (= many GB at 1MB payload) and overflow the
    // slab, leaving subsequent GETs missing -> bogus "high" read bandwidth
    // reported because server replies are mostly 5-byte "not found".
    bool        shared_keyspace = false;
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
        else if (k == "--prio")     o.prio = v;
        else if (k == "--shared-keyspace") o.shared_keyspace =
            (v.empty() || v == "1" || v == "true");
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
// Returns the number of response bytes received (not counting the 4-byte
// length header) on success, or -1 on failure.  nr_bench uses this to
// compute the *actual* bytes-per-second moved through the UDS, which is
// what the bandwidth-oriented tests (perf_06) need -- otherwise a GET
// that misses (server returns a short "not found" response) would be
// counted as if it returned the requested val_size worth of bytes.
static int64_t rpc_call(int fd, const char* kind, const void* body, size_t blen) {
    uint32_t kl = (uint32_t)std::strlen(kind);
    if (write_all(fd, &kl, 4) < 0) return -1;
    if (write_all(fd, kind, kl) < 0) return -1;
    uint32_t bl = (uint32_t)blen;
    if (write_all(fd, &bl, 4) < 0) return -1;
    if (bl && write_all(fd, body, bl) < 0) return -1;
    uint32_t rl = 0;
    if (read_all(fd, &rl, 4) < 0) return -1;
    // Drain and discard response body.
    std::vector<char> buf(rl);
    if (rl && read_all(fd, buf.data(), rl) < 0) return -1;
    return (int64_t)rl;
}

static inline uint64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

int main(int argc, char** argv) {
    Opt o; parse(argc, argv, o);
    std::printf("[nr_bench] uds=%s op=%s threads=%d duration=%ds "
                "val_size=%d keyspace=%d%s prio=%s\n",
                o.uds.c_str(), o.op.c_str(), o.threads, o.duration,
                o.val_size, o.keyspace,
                o.shared_keyspace ? "(shared)" : "",
                o.prio.empty() ? "default" : o.prio.c_str());

    std::atomic<bool> stop{false};
    std::atomic<uint64_t> ops_done{0};
    std::atomic<uint64_t> ops_fail{0};
    std::atomic<uint64_t> bytes_resp{0};   // sum of response payload bytes
    std::atomic<uint64_t> bytes_req{0};    // sum of request payload bytes
    std::vector<std::vector<uint32_t>> lats(o.threads); // per-thread ns samples

    // Pre-generate a value buffer.
    std::string val(o.val_size, 'X');

    // Build suffix once; worker threads can just append it to the RPC kind.
    std::string prio_suffix;
    if (o.prio == "hi")      prio_suffix = "_HI";
    else if (o.prio == "lo") prio_suffix = "_LO";

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
            int kn;
            if (o.shared_keyspace) {
                // One global keyspace: key_id alone determines the key, so
                // all threads (and all phases: PUT warmup + GET read) touch
                // the same N objects. Bounded memory footprint = keyspace *
                // val_size, which makes perf_06 reproducible without
                // overflowing the slab.
                kn = std::snprintf(keybuf, sizeof(keybuf), "bk_%d", key_id);
            } else {
                // Per-thread keyspace: each worker has its own cone of
                // keys ("bk_<tid>_<id>"). Useful when we want threads not
                // to contend on the same slab slot (perf_01/02/03).
                kn = std::snprintf(keybuf, sizeof(keybuf), "bk_%d_%d", tid, key_id);
            }
            body.clear();
            body.insert(body.end(), keybuf, keybuf + kn);

            std::string kind = "RPC_KV_PUT";
            if (o.op == "get") {
                kind = "RPC_KV_GET";
                // body: just the key
            } else if (o.op == "get-raw") {
                // Raw GET: server returns [1-byte status][4-byte size][payload]
                // so the client's UDS read actually transfers the full bytes.
                // Use this for bandwidth measurements (perf_06) where the
                // JSON-formatted RPC_KV_GET response would under-count.
                kind = "RPC_KV_GET_RAW";
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
            // QoS: append priority suffix so the data plane can pick a
            // dedicated QP for hi-prio traffic vs rate-limited lo-prio.
            kind += prio_suffix;

            uint64_t t0 = now_ns();
            int64_t recv = rpc_call(fd, kind.c_str(), body.data(), body.size());
            uint64_t dt = now_ns() - t0;
            bool ok = (recv >= 0);
            if (ok) {
                ops_done.fetch_add(1, std::memory_order_relaxed);
                bytes_resp.fetch_add((uint64_t)recv, std::memory_order_relaxed);
                bytes_req.fetch_add(body.size(), std::memory_order_relaxed);
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
    // Bytes-based bandwidth: this is what the UDS really moved, not an
    // assumed ops*val_size product. For GETs where the key misses, the
    // server only returns 5 bytes and that's what gets counted here.
    uint64_t tx = bytes_req.load();
    uint64_t rx = bytes_resp.load();
    std::printf("  req_bytes     : %lu (%.2f MB/s)\n",
                (unsigned long)tx, tx / elapsed / 1e6);
    std::printf("  resp_bytes    : %lu (%.2f MB/s)\n",
                (unsigned long)rx, rx / elapsed / 1e6);
    std::printf("  latency us    : avg=%.2f  p50=%.2f  p99=%.2f  p99.9=%.2f  max=%.2f\n",
                avg_us, p50, p99, p999, pmax);
    return 0;
}
