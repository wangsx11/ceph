#include "io_scheduler.h"
#include "../common/logger.h"

namespace nr {

// NOTE: Skeleton. Full io_uring bring-up (setup, SQPOLL, ring polling thread)
// will land together with TierEngine's NVMe path. For W1 we keep a stub so
// the data plane links and the unit tests pass.

bool IoScheduler::init(const Config& cfg) {
    NR_INFO("IoScheduler init fg=%s bg=%s sq_depth=%d sq_poll=%d",
            cfg.fg_path.c_str(), cfg.bg_path.c_str(),
            cfg.sq_depth, (int)cfg.sq_poll_fg);
    return true;
}
void IoScheduler::shutdown() {}

int IoScheduler::async_write(Prio, const void*, size_t, uint64_t, OnDone cb) {
    if (cb) cb(0);
    return 0;
}
int IoScheduler::async_read (Prio, void*, size_t, uint64_t, OnDone cb) {
    if (cb) cb(0);
    return 0;
}
int IoScheduler::sync_write (Prio, const void*, size_t, uint64_t) { return 0; }
int IoScheduler::sync_read  (Prio, void*,       size_t, uint64_t) { return 0; }

} // namespace nr
