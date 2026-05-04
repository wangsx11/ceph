#pragma once

#include "rdma/rdma_core.h"

#include <cstddef>
#include <cstdint>
#include <string>

namespace nr {

struct GpuDirectInfo {
    bool enabled = false;
    bool compiled = false;
    bool peermem_loaded = false;
    int device_id = -1;
    int cuda_driver_version = 0;
    int cuda_runtime_version = 0;
    std::string device_name;
    std::string error;
    uint64_t base_addr = 0;
    uint64_t len = 0;
    uint32_t lkey = 0;
    uint32_t rkey = 0;
};

struct GpuValidateResult {
    bool ok = false;
    uint64_t bytes = 0;
    uint64_t offset = 0;
    uint32_t seed = 0;
    uint64_t checksum = 0;
    uint64_t mismatches = 0;
    uint64_t first_bad = UINT64_MAX;
    uint32_t expected_first = 0;
    uint32_t actual_first = 0;
    uint64_t validate_ns = 0;
    std::string error;
};

uint8_t gdr_pattern_byte(uint64_t absolute_offset, uint32_t seed);
bool gpu_direct_compiled();
bool gpu_peer_memory_loaded();

class GpuDirectBuffer {
public:
    GpuDirectBuffer() = default;
    GpuDirectBuffer(const GpuDirectBuffer&) = delete;
    GpuDirectBuffer& operator=(const GpuDirectBuffer&) = delete;
    ~GpuDirectBuffer() = default;

    bool init(RdmaCore& core, int device_id, size_t len);
    void shutdown(RdmaCore& core);

    const GpuDirectInfo& info() const { return info_; }
    GpuValidateResult validate_pattern(uint64_t offset, size_t len, uint32_t seed) const;

private:
    void* device_ptr_ = nullptr;
    MrHandle mr_{};
    GpuDirectInfo info_{};
};

} // namespace nr
