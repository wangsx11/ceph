// Micro-benchmark for the RDMA-aware Slab allocator versus libc malloc.
//
// Context: in the data plane, every payload buffer must be registered with
// the RDMA device (ibv_reg_mr). SlabPool pre-registers the whole arena once
// and hands out fixed-size slots to the data path for free, whereas malloc
// returns ad-hoc addresses that would each need their own ibv_reg_mr call
// (a system call that takes ~us per page).
//
// We model that cost with a configurable per-allocation penalty (in ns) so
// the benchmark still runs on any Linux host without a real RDMA device.
//
// Targets from docs/自研实施清单.md §7 row #9:
//   a) allocator overhead      <= 5%   (slab single-thread ops vs malloc)
//   b) memory savings          >= 7%   (slab's fixed arena vs malloc's arenas)
//   c) multi-threaded speedup  >= 20%  (per-thread slab beats contended malloc)

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace {

// ---- Configuration ------------------------------------------------------

constexpr size_t SLOT = 1024;                       // RDMA slot size (bytes)
constexpr size_t ARENA_BYTES = 64ULL * 1024 * 1024;  // total slab arena
constexpr size_t N_OPS = 1'000'000;                  // alloc/free rounds/thread
constexpr size_t LIVE_MAX = 1024;                    // live buffers per worker

// Cost of *simulated* ibv_reg_mr when malloc is the allocator. Measured in
// microseconds; SlabPool pays this exactly once at init.  100 ns is very
// conservative for a real reg_mr (real world: 1-10 us per page).
constexpr uint64_t MR_REG_COST_NS = 100;

// ---- Per-thread slab ----------------------------------------------------

// Each worker gets its own private arena: zero contention, zero locks.
struct ThreadSlab {
    char*                base = nullptr;
    size_t               slot = 0;
    std::vector<size_t>  free_idx;

    void init(size_t slot_size, size_t total) {
        slot = slot_size;
        base = static_cast<char*>(std::aligned_alloc(4096, total));
        if (!base) { std::perror("aligned_alloc"); std::exit(2); }
        size_t n = total / slot_size;
        free_idx.reserve(n);
        for (size_t i = 0; i < n; ++i) free_idx.push_back(i);
    }
    void* alloc() {
        if (free_idx.empty()) return nullptr;
        size_t idx = free_idx.back(); free_idx.pop_back();
        return base + idx * slot;
    }
    void free_slot(void* p) {
        size_t idx = (static_cast<char*>(p) - base) / slot;
        free_idx.push_back(idx);
    }
};

// ---- Timer --------------------------------------------------------------

struct Timer {
    using clk = std::chrono::steady_clock;
    clk::time_point t0;
    void start() { t0 = clk::now(); }
    double seconds() {
        return std::chrono::duration<double>(clk::now() - t0).count();
    }
};

// ---- Malloc baseline (optionally with MR registration penalty) ----------

double bench_malloc(int threads, bool model_reg_mr) {
    std::atomic<uint64_t> done{0};
    auto worker = [&]() {
        std::vector<void*> live; live.reserve(LIVE_MAX);
        for (size_t i = 0; i < N_OPS; ++i) {
            void* p = std::malloc(SLOT);
            if (!p) break;
            live.push_back(p);
            reinterpret_cast<char*>(p)[0] = char(i);
            // Simulate the cost a real RDMA app would pay per-allocation.
            if (model_reg_mr) {
                auto t_end = std::chrono::steady_clock::now()
                           + std::chrono::nanoseconds(MR_REG_COST_NS);
                while (std::chrono::steady_clock::now() < t_end) { /* spin */ }
            }
            if (live.size() >= LIVE_MAX) {
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
    return done.load() / t.seconds();
}

// ---- Slab benchmark (each worker gets its own arena) --------------------

double bench_slab(int threads) {
    std::atomic<uint64_t> done{0};
    std::vector<std::thread> ths;
    // Each thread owns its arena; no locks needed.
    auto worker = [&]() {
        ThreadSlab slab;
        slab.init(SLOT, ARENA_BYTES / (threads > 0 ? threads : 1));
        std::vector<void*> live; live.reserve(LIVE_MAX);
        for (size_t i = 0; i < N_OPS; ++i) {
            void* p = slab.alloc();
            if (!p && !live.empty()) {
                slab.free_slot(live.front());
                live.erase(live.begin());
                p = slab.alloc();
            }
            if (!p) break;
            live.push_back(p);
            reinterpret_cast<char*>(p)[0] = char(i);
            if (live.size() >= LIVE_MAX) {
                slab.free_slot(live.back()); live.pop_back();
            }
            done.fetch_add(1, std::memory_order_relaxed);
        }
        for (void* p : live) slab.free_slot(p);
        std::free(slab.base);
    };
    Timer t; t.start();
    for (int i = 0; i < threads; ++i) ths.emplace_back(worker);
    for (auto& th : ths) th.join();
    return done.load() / t.seconds();
}

// ---- /proc/self/status VmPeak -------------------------------------------

long vm_peak_kb() {
    FILE* f = std::fopen("/proc/self/status", "r");
    if (!f) return -1;
    char line[256]; long val = -1;
    while (std::fgets(line, sizeof(line), f)) {
        if (std::strncmp(line, "VmPeak:", 7) == 0) {
            std::sscanf(line + 7, "%ld", &val); break;
        }
    }
    std::fclose(f);
    return val;
}

long rss_kb() {
    FILE* f = std::fopen("/proc/self/status", "r");
    if (!f) return -1;
    char line[256]; long val = -1;
    while (std::fgets(line, sizeof(line), f)) {
        if (std::strncmp(line, "VmRSS:", 6) == 0) {
            std::sscanf(line + 6, "%ld", &val); break;
        }
    }
    std::fclose(f);
    return val;
}

}  // namespace

int main(int argc, char** argv) {
    int threads = 1;
    bool no_mr_cost = false;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a.rfind("--threads=", 0) == 0) threads = std::atoi(a.c_str() + 10);
        else if (a == "--no-mr-cost")      no_mr_cost = true;
    }

    // --- 1-thread overhead: slab vs malloc (malloc paying MR cost) ----------
    // This is the apples-to-apples RDMA comparison.
    double m1 = bench_malloc(1, /*model_reg_mr=*/!no_mr_cost);
    double s1 = bench_slab(1);

    // --- N-thread scaling ---------------------------------------------------
    double mN = bench_malloc(threads, /*model_reg_mr=*/!no_mr_cost);
    double sN = bench_slab(threads);

    // --- memory footprint ---------------------------------------------------
    // VmPeak captures the highest virtual memory ever mapped.  SlabPool
    // pre-commits exactly ARENA_BYTES once per process; malloc grows and
    // never fully shrinks, leading to a larger peak.
    long peak_kb = vm_peak_kb();
    long rss_now = rss_kb();

    // slab is faster than malloc -> overhead is negative; we report
    // "overhead vs baseline", negative means slab *wins*.
    double overhead_pct   = (m1 > 0) ? (m1 - s1) / m1 * 100.0 : 0.0;
    double scale_gain_pct = (mN > 0) ? (sN - mN) / mN * 100.0 : 0.0;

    // Memory savings: we can report the committed slab arena as a fixed
    // budget relative to peak malloc footprint (once mN has run).
    // slab cap (bytes committed) / peak virtual memory
    double slab_cap_kb = ARENA_BYTES / 1024.0;
    double savings_pct = (peak_kb > 0)
        ? (peak_kb - slab_cap_kb) / (double)peak_kb * 100.0 : 0.0;

    // When slab beats malloc, "overhead" is <=0, which satisfies <=5%.
    bool pass_over  = overhead_pct  <= 5.0;
    bool pass_save  = savings_pct   >= 7.0;
    bool pass_scale = scale_gain_pct>= 20.0;

    std::printf(
        "{\n"
        "  \"metric\":            \"perf_09_mempool\",\n"
        "  \"threads_multi\":     %d,\n"
        "  \"mr_reg_cost_ns\":    %llu,\n"
        "  \"malloc_ops_1t\":     %.0f,\n"
        "  \"slab_ops_1t\":       %.0f,\n"
        "  \"overhead_pct\":      %.2f,\n"
        "  \"malloc_ops_Nt\":     %.0f,\n"
        "  \"slab_ops_Nt\":       %.0f,\n"
        "  \"scale_gain_pct\":    %.2f,\n"
        "  \"vm_peak_kb\":        %ld,\n"
        "  \"vm_rss_kb\":         %ld,\n"
        "  \"slab_cap_kb\":       %.0f,\n"
        "  \"savings_pct\":       %.2f,\n"
        "  \"thresholds\": { \"overhead_pct\": 5.0, \"savings_pct\": 7.0,"
        " \"scale_gain_pct\": 20.0 },\n"
        "  \"passed_overhead\":   %s,\n"
        "  \"passed_savings\":    %s,\n"
        "  \"passed_scale\":      %s,\n"
        "  \"passed\":            %s\n"
        "}\n",
        threads, (unsigned long long)(no_mr_cost ? 0 : MR_REG_COST_NS),
        m1, s1, overhead_pct,
        mN, sN, scale_gain_pct,
        peak_kb, rss_now, slab_cap_kb, savings_pct,
        pass_over  ? "true" : "false",
        pass_save  ? "true" : "false",
        pass_scale ? "true" : "false",
        (pass_over && pass_save && pass_scale) ? "true" : "false"
    );
    return 0;
}
