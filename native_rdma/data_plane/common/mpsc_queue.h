#pragma once
#include <atomic>
#include <cstddef>

namespace nr {

// Multi-producer single-consumer bounded lock-free queue.
// Capacity must be a power of two.
template <typename T, size_t Capacity>
class MpscQueue {
    static_assert((Capacity & (Capacity - 1)) == 0,
                  "Capacity must be a power of two");
public:
    MpscQueue() {
        for (size_t i = 0; i < Capacity; ++i)
            seq_[i].store(i, std::memory_order_relaxed);
    }

    bool push(const T& v) {
        Cell* cell;
        size_t pos = enqueue_pos_.load(std::memory_order_relaxed);
        for (;;) {
            cell = &cells_[pos & (Capacity - 1)];
            size_t seq = cell->seq.load(std::memory_order_acquire);
            intptr_t dif = (intptr_t)seq - (intptr_t)pos;
            if (dif == 0) {
                if (enqueue_pos_.compare_exchange_weak(
                        pos, pos + 1,
                        std::memory_order_relaxed)) break;
            } else if (dif < 0) {
                return false; // full
            } else {
                pos = enqueue_pos_.load(std::memory_order_relaxed);
            }
        }
        cell->data = v;
        cell->seq.store(pos + 1, std::memory_order_release);
        return true;
    }

    bool pop(T& out) {
        size_t pos = dequeue_pos_.load(std::memory_order_relaxed);
        Cell* cell = &cells_[pos & (Capacity - 1)];
        size_t seq = cell->seq.load(std::memory_order_acquire);
        intptr_t dif = (intptr_t)seq - (intptr_t)(pos + 1);
        if (dif == 0) {
            dequeue_pos_.store(pos + 1, std::memory_order_relaxed);
            out = cell->data;
            cell->seq.store(pos + Capacity, std::memory_order_release);
            return true;
        }
        return false; // empty (or contended; caller may retry)
    }

private:
    struct Cell {
        std::atomic<size_t> seq;
        T data;
    };
    alignas(64) Cell cells_[Capacity];
    alignas(64) std::atomic<size_t> enqueue_pos_{0};
    alignas(64) std::atomic<size_t> dequeue_pos_{0};
    // seq_ kept as parallel array only for init; keep here for clarity
    alignas(64) std::atomic<size_t> seq_[Capacity];
};

} // namespace nr
