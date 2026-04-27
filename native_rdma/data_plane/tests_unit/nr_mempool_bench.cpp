// Micro-benchmark for the Slab allocator algorithm versus libc malloc.
//
// Validates mempool performance targets in docs/自研实施清单.md §7 row #9:
//   a) allocator overhead      <= 5%   (ops/s loss vs malloc at single thread)
//   b) memory savings          >= 7%   (slab pre-commits exact bytes; malloc
//                                       grows the heap with per-chunk headers
//                                       + glibc arenas)
//   c) multi-threaded speedup  >= 20%  (slab avoids malloc arena contention)
//
// This is a *self-contained* benchmark: it does NOT need RDMA or HugePages,
// which lets CI exercise the core allocator logic on any Linux host.
//
// Output is a single JSON document on stdout suitable for the perf summary.

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <stack>
#include <string>
#include <thread>
#include <vector>

namespace {

// Stack-based slab allocator: same data structure as nr::SlabPool but
// sitting on plain aligned_alloc, so we can run it standalone.
class SlabStandalone {
public:
    void init(size_t slot_size, size_t total_bytes) {
        slot_size_   = slot_size;
        total_bytes_ = total_bytes;
        // 4K alignment is enough for the purposes of this bench.
        base_ = static_cast<char*>(std::aligned_alloc(4096, total_bytes));
        if (!base_) { std::perror("aligned_alloc"); std::exit(2); }
        size_t nslots = total_bytes / slot_size;
        free_.reserve(nslots);
        for (size_t i = 0; i < nslots; ++i) free_.push_back(i);
    }
    void* alloc() {
        std::lock_guard<std::mutex> lk(mu_);
        if (free_.empty()) return nullptr;
        size_t idx = free_.back();
        free_.pop_back();
        return base_ + idx * slot_size_;
    }
    void free_slot(void* p) {
        std::lock_guard<std::mutex> lk(mu_);
        size_t idx = (static_cast<char*>(p) - base_) / slot_size_;
        free_.push_back(idx);
    }
    size_t bytes_committed() const { return total_bytes_; }

private:
    char*                base_ = nullptr;
    size_t               slot_size_   = 0;
    size_t               total_bytes_ = 0;
    std::vector<size_t>  free_;
    std::mutex           mu_;
};

struct Timer {
    using clk = std::chrono::steady_clock;
    clk::time_point t0;
    void start() { t0 = clk::now(); }
    double seconds() {
        return std::chrono::duration<double>(clk::now() - t0).count();
    }
};

constexpr size_t SLOT = 1024;
constexpr size_t TOTAL = 64ULL * 1024 * 1024;   // 64 MB, ~65k slots
constexpr size_t N_OPS = 2'000'000;              // per thread

double bench_malloc(int threads) {
    std::atomic<uint64_t> done{0};
    auto worker = [&]() {
        std::vector<void*> live; live.reserve(1024);
        for (size_t i = 0; i < N_OPS; ++i) {
            void* p = std::malloc(SLOT);
            if (!p) break;
            live.push_back(p);
            // Touch one byte to force real commit.
            reinterpret_cast<char*>(p)[0] = char(i);
            if (live.size() >= 1024) {
                std::free(live.back()); live.pop_back();
            }
            done.fetch_add(1, std::memory_order_relaxed);
        }
        for (void* p : live) std::free(p);
    };
    Timer t; t.start();
    std::vector<std::thread> ths;
    for (int i = 0; i < threads; ++i) ths.emplace_back(worker);
    for (auto& th : ths) th.join();
    double secs = t.seconds();
    return done.load() / secs;    // ops/s total
}

double bench_slab(SlabStandalone& slab, int threads) {
    std::atomic<uint64_t> done{0};
    auto worker = [&]() {
        std::vector<void*> live; live.reserve(1024);
        for (size_t i = 0; i < N_OPS; ++i) {
            void* p = slab.alloc();
            if (!p) {
                // Fully reserved -- free oldest and retry once.
                if (!live.empty()) { slab.free_slot(live.front());
                                     live.erase(live.begin()); }
                p = slab.alloc();
                if (!p) break;
            }
            live.push_back(p);
            reinterpret_cast<char*>(p)[0] = char(i);
            if (live.size() >= 1024) {
                slab.free_slot(live.back()); live.pop_back();
            }
            done.fetch_add(1, std::memory_order_relaxed);
        }
        for (void* p : live) slab.free_slot(p);
    };
    Timer t; t.start();
    std::vector<std::thread> ths;
    for (int i = 0; i < threads; ++i) ths.emplace_back(worker);
    for (auto& th : ths) th.join();
    double secs = t.seconds();
    return done.load() / secs;
}

// Inspect /proc/self/status VmRSS to gauge resident memory used.
long rss_kb() {
    FILE* f = std::fopen("/proc/self/status", "r");
    if (!f) return -1;
    char line[256]; long val = -1;
    while (std::fgets(line, sizeof(line), f)) {
        if (std::strncmp(line, "VmRSS:", 6) == 0) {
            std::sscanf(line + 6, "%ld", &val);
            break;
        }
    }
    std::fclose(f);
    return val;
}

}  // namespace

int main(int argc, char** argv) {
    int threads = 1;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a.rfind("--threads=", 0) == 0) threads = std::atoi(a.c_str() + 10);
    }

    long rss0 = rss_kb();

    // --- single-thread overhead (target: slab/malloc_ops_loss <= 5%) ---
    double m1 = bench_malloc(1);
    long   rss_malloc = rss_kb();
    SlabStandalone slab;
    slab.init(SLOT, TOTAL);
    double s1 = bench_slab(slab, 1);
    long   rss_slab   = rss_kb();

    // --- multi-thread scale (target: slab wins >= 20% at the chosen N) ---
    double mN = bench_malloc(threads);
    double sN = bench_slab(slab, threads);

    // Slab is faster than malloc -> loss is negative; floor at 0 for display.
    double overhead_pct  = (m1 > 0) ? (m1 - s1) / m1 * 100.0 : 0.0;
    double savings_pct   = (rss_malloc > 0)
        ? (double)(rss_malloc - rss_slab) / rss_malloc * 100.0 : 0.0;
    double scale_gain_pct = (mN > 0) ? (sN - mN) / mN * 100.0 : 0.0;

    std::printf(
        "{\n"
        "  \"metric\":            \"perf_09_mempool\",\n"
        "  \"threads_multi\":     %d,\n"
        "  \"malloc_ops_1t\":     %.0f,\n"
        "  \"slab_ops_1t\":       %.0f,\n"
        "  \"overhead_pct\":      %.2f,\n"
        "  \"malloc_ops_Nt\":     %.0f,\n"
        "  \"slab_ops_Nt\":       %.0f,\n"
        "  \"scale_gain_pct\":    %.2f,\n"
        "  \"rss_kb_baseline\":   %ld,\n"
        "  \"rss_kb_after_malloc\":%ld,\n"
        "  \"rss_kb_after_slab\": %ld,\n"
        "  \"savings_pct\":       %.2f,\n"
        "  \"thresholds\": { \"overhead_pct\": 5.0, \"savings_pct\": 7.0,"
        " \"scale_gain_pct\": 20.0 },\n"
        "  \"passed_overhead\":   %s,\n"
        "  \"passed_savings\":    %s,\n"
        "  \"passed_scale\":      %s,\n"
        "  \"passed\":            %s\n"
        "}\n",
        threads,
        m1, s1, overhead_pct,
        mN, sN, scale_gain_pct,
        rss0, rss_malloc, rss_slab, savings_pct,
        (overhead_pct  <= 5.0)  ? "true" : "false",
        (savings_pct   >= 7.0)  ? "true" : "false",
        (scale_gain_pct>= 20.0) ? "true" : "false",
        ((overhead_pct <= 5.0) && (savings_pct >= 7.0)
                              && (scale_gain_pct >= 20.0)) ? "true" : "false"
    );
    return 0;
}
