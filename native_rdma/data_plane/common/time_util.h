#pragma once
#include <cstdint>
#include <chrono>

namespace nr {

inline uint64_t now_ns() {
    auto tp = std::chrono::steady_clock::now().time_since_epoch();
    return std::chrono::duration_cast<std::chrono::nanoseconds>(tp).count();
}

inline uint64_t now_us() { return now_ns() / 1000ULL; }
inline uint64_t now_ms() { return now_ns() / 1000000ULL; }

// Monotonic TSC (x86). Good for sub-μs intervals in a single core.
#if defined(__x86_64__)
inline uint64_t rdtsc() {
    uint32_t lo, hi;
    __asm__ __volatile__ ("rdtsc" : "=a"(lo), "=d"(hi));
    return ((uint64_t)hi << 32) | lo;
}
#else
inline uint64_t rdtsc() { return now_ns(); }
#endif

} // namespace nr
