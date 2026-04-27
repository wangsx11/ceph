#pragma once
#include <cstdint>

namespace nr {

// Lossless capture of entity state during simulation runs.
class SimCapture {
public:
    // Thread-local producer; returns false if the ring is full (backpressure).
    bool push(uint64_t entity_id, uint32_t type,
              const void* attr_blob, size_t len);

    // Background consumer: flush to NVMe WAL (called periodically).
    void flush();
};

} // namespace nr
