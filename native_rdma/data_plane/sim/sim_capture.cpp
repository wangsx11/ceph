#include "sim_capture.h"

namespace nr {
bool SimCapture::push(uint64_t, uint32_t, const void*, size_t) {
    // TODO: thread-local SPSC ring -> batch flush to NVMe.
    return true;
}
void SimCapture::flush() { /* TODO */ }
} // namespace nr
