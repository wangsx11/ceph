#include "gpu_direct.h"

#include <unistd.h>

namespace nr {

uint8_t gdr_pattern_byte(uint64_t absolute_offset, uint32_t seed) {
    return static_cast<uint8_t>(
        (absolute_offset * 1315423911ULL + (absolute_offset >> 8) + seed) & 0xffU);
}

bool gpu_direct_compiled() {
    return false;
}

bool gpu_peer_memory_loaded() {
    return access("/sys/module/nvidia_peermem", F_OK) == 0 ||
           access("/sys/module/nv_peer_mem", F_OK) == 0;
}

bool GpuDirectBuffer::init(RdmaCore&, int device_id, size_t len) {
    info_ = {};
    info_.compiled = false;
    info_.peermem_loaded = gpu_peer_memory_loaded();
    info_.device_id = device_id;
    info_.len = len;
    info_.error = "NR_USE_CUDA=OFF";
    return false;
}

void GpuDirectBuffer::shutdown(RdmaCore&) {
    device_ptr_ = nullptr;
    mr_ = {};
    info_ = {};
}

GpuValidateResult GpuDirectBuffer::validate_pattern(
    uint64_t offset, size_t len, uint32_t seed) const {
    GpuValidateResult out{};
    out.offset = offset;
    out.bytes = len;
    out.seed = seed;
    out.error = "NR_USE_CUDA=OFF";
    return out;
}

} // namespace nr
