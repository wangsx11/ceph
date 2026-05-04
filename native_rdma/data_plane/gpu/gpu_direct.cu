#include "gpu_direct.h"

#include "common/logger.h"
#include "common/time_util.h"

#include <cuda_runtime.h>

#include <climits>
#include <cstring>
#include <unistd.h>

namespace nr {

namespace {

struct DeviceValidateState {
    unsigned long long checksum;
    unsigned long long mismatches;
    unsigned long long first_bad;
    unsigned int expected_first;
    unsigned int actual_first;
};

__host__ __device__ inline unsigned char gdr_pattern_byte_impl(
    unsigned long long absolute_offset, unsigned int seed) {
    return static_cast<unsigned char>(
        (absolute_offset * 1315423911ULL + (absolute_offset >> 8) + seed) & 0xffU);
}

__global__ void validate_pattern_kernel(
    const unsigned char* base,
    unsigned long long offset,
    unsigned long long len,
    unsigned int seed,
    DeviceValidateState* out) {
    unsigned long long tid =
        static_cast<unsigned long long>(blockIdx.x) * blockDim.x + threadIdx.x;
    unsigned long long stride =
        static_cast<unsigned long long>(blockDim.x) * gridDim.x;
    unsigned long long local_sum = 0;
    unsigned long long local_mismatches = 0;
    unsigned long long local_first = ULLONG_MAX;
    unsigned int local_expected = 0;
    unsigned int local_actual = 0;

    for (unsigned long long i = tid; i < len; i += stride) {
        unsigned char actual = base[offset + i];
        unsigned char expected = gdr_pattern_byte_impl(offset + i, seed);
        local_sum += actual;
        if (actual != expected) {
            ++local_mismatches;
            if (i < local_first) {
                local_first = i;
                local_expected = expected;
                local_actual = actual;
            }
        }
    }

    atomicAdd(&out->checksum, local_sum);
    atomicAdd(&out->mismatches, local_mismatches);
    if (local_first != ULLONG_MAX) {
        unsigned long long old = atomicMin(&out->first_bad, local_first);
        if (local_first < old) {
            out->expected_first = local_expected;
            out->actual_first = local_actual;
        }
    }
}

static const char* cuda_err(cudaError_t err) {
    return cudaGetErrorString(err);
}

static bool cuda_ok(cudaError_t err, std::string* error) {
    if (err == cudaSuccess) return true;
    if (error) *error = cuda_err(err);
    return false;
}

} // namespace

uint8_t gdr_pattern_byte(uint64_t absolute_offset, uint32_t seed) {
    return gdr_pattern_byte_impl(absolute_offset, seed);
}

bool gpu_direct_compiled() {
    return true;
}

bool gpu_peer_memory_loaded() {
    return access("/sys/module/nvidia_peermem", F_OK) == 0 ||
           access("/sys/module/nv_peer_mem", F_OK) == 0;
}

bool GpuDirectBuffer::init(RdmaCore& core, int device_id, size_t len) {
    info_ = {};
    info_.compiled = true;
    info_.peermem_loaded = gpu_peer_memory_loaded();
    info_.device_id = device_id;
    info_.len = len;

    std::string err;
    int driver = 0;
    int runtime = 0;
    if (!cuda_ok(cudaDriverGetVersion(&driver), &err)) {
        info_.error = "cudaDriverGetVersion failed: " + err;
        return false;
    }
    if (!cuda_ok(cudaRuntimeGetVersion(&runtime), &err)) {
        info_.error = "cudaRuntimeGetVersion failed: " + err;
        return false;
    }
    info_.cuda_driver_version = driver;
    info_.cuda_runtime_version = runtime;

    int count = 0;
    if (!cuda_ok(cudaGetDeviceCount(&count), &err)) {
        info_.error = "cudaGetDeviceCount failed: " + err;
        return false;
    }
    if (device_id < 0 || device_id >= count) {
        info_.error = "bad CUDA device id";
        return false;
    }
    if (!cuda_ok(cudaSetDevice(device_id), &err)) {
        info_.error = "cudaSetDevice failed: " + err;
        return false;
    }
    cudaDeviceProp prop{};
    if (!cuda_ok(cudaGetDeviceProperties(&prop, device_id), &err)) {
        info_.error = "cudaGetDeviceProperties failed: " + err;
        return false;
    }
    info_.device_name = prop.name;

    if (!cuda_ok(cudaMalloc(&device_ptr_, len), &err)) {
        info_.error = "cudaMalloc failed: " + err;
        return false;
    }
    if (!cuda_ok(cudaMemset(device_ptr_, 0, len), &err) ||
        !cuda_ok(cudaDeviceSynchronize(), &err)) {
        info_.error = "cudaMemset failed: " + err;
        cudaFree(device_ptr_);
        device_ptr_ = nullptr;
        return false;
    }

    mr_ = core.reg_mr(device_ptr_, len);
    if (!mr_.mr) {
        info_.error = "ibv_reg_mr(cudaMalloc_ptr) failed";
        cudaFree(device_ptr_);
        device_ptr_ = nullptr;
        return false;
    }

    info_.enabled = true;
    info_.base_addr = reinterpret_cast<uint64_t>(device_ptr_);
    info_.len = len;
    info_.lkey = mr_.lkey;
    info_.rkey = mr_.rkey;
    NR_INFO("GpuDirectBuffer ready: dev=%d name=%s ptr=%p len=%zu lkey=0x%x rkey=0x%x peermem=%s",
            device_id, info_.device_name.c_str(), device_ptr_, len,
            info_.lkey, info_.rkey, info_.peermem_loaded ? "true" : "false");
    return true;
}

void GpuDirectBuffer::shutdown(RdmaCore& core) {
    if (mr_.mr) core.dereg_mr(mr_);
    if (device_ptr_) {
        cudaSetDevice(info_.device_id);
        cudaFree(device_ptr_);
    }
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
    if (!info_.enabled || !device_ptr_) {
        out.error = "GPU Direct buffer is not enabled";
        return out;
    }
    if (offset > info_.len || len > info_.len - offset) {
        out.error = "validate range exceeds GPU buffer";
        return out;
    }

    std::string err;
    if (!cuda_ok(cudaSetDevice(info_.device_id), &err)) {
        out.error = "cudaSetDevice failed: " + err;
        return out;
    }

    DeviceValidateState host{};
    host.first_bad = ULLONG_MAX;
    DeviceValidateState* dev = nullptr;
    if (!cuda_ok(cudaMalloc(&dev, sizeof(*dev)), &err)) {
        out.error = "cudaMalloc(validate state) failed: " + err;
        return out;
    }
    if (!cuda_ok(cudaMemcpy(dev, &host, sizeof(host), cudaMemcpyHostToDevice), &err)) {
        out.error = "cudaMemcpy(validate state H2D) failed: " + err;
        cudaFree(dev);
        return out;
    }

    uint64_t t0 = now_ns();
    int threads = 256;
    int blocks = static_cast<int>((len + threads - 1) / threads);
    if (blocks < 1) blocks = 1;
    if (blocks > 4096) blocks = 4096;
    validate_pattern_kernel<<<blocks, threads>>>(
        static_cast<const unsigned char*>(device_ptr_),
        offset,
        static_cast<unsigned long long>(len),
        seed,
        dev);
    cudaError_t launch = cudaGetLastError();
    if (launch != cudaSuccess) {
        out.error = std::string("validate kernel launch failed: ") + cuda_err(launch);
        cudaFree(dev);
        return out;
    }
    if (!cuda_ok(cudaDeviceSynchronize(), &err)) {
        out.error = "validate kernel failed: " + err;
        cudaFree(dev);
        return out;
    }
    if (!cuda_ok(cudaMemcpy(&host, dev, sizeof(host), cudaMemcpyDeviceToHost), &err)) {
        out.error = "cudaMemcpy(validate state D2H) failed: " + err;
        cudaFree(dev);
        return out;
    }
    out.validate_ns = now_ns() - t0;
    cudaFree(dev);

    out.checksum = host.checksum;
    out.mismatches = host.mismatches;
    out.first_bad = host.first_bad;
    out.expected_first = host.expected_first;
    out.actual_first = host.actual_first;
    out.ok = (host.mismatches == 0);
    if (!out.ok) out.error = "GPU pattern mismatch";
    return out;
}

} // namespace nr
