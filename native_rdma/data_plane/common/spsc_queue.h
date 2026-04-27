#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <new>

namespace nr {

// A fixed-capacity single-producer single-consumer lock-free ring.
// Capacity must be a power of two. Elements must be trivially copyable
// (or cheap to move) for the hot path.
template <typename T, size_t Capacity>
class SpscQueue {
    static_assert((Capacity & (Capacity - 1)) == 0,
                  "Capacity must be a power of two");
public:
    SpscQueue() = default;

    bool push(const T& v) {
        const size_t h = head_.load(std::memory_order_relaxed);
        const size_t t = tail_.load(std::memory_order_acquire);
        if (h - t == Capacity) return false;   // full
        buf_[h & (Capacity - 1)] = v;
        head_.store(h + 1, std::memory_order_release);
        return true;
    }

    bool pop(T& out) {
        const size_t t = tail_.load(std::memory_order_relaxed);
        const size_t h = head_.load(std::memory_order_acquire);
        if (h == t) return false;              // empty
        out = buf_[t & (Capacity - 1)];
        tail_.store(t + 1, std::memory_order_release);
        return true;
    }

    size_t size() const {
        return head_.load(std::memory_order_acquire) -
               tail_.load(std::memory_order_acquire);
    }

private:
    alignas(64) std::atomic<size_t> head_{0};
    alignas(64) std::atomic<size_t> tail_{0};
    alignas(64) T buf_[Capacity];
};

} // namespace nr
