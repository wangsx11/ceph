#include "snapshot.h"
#include "../common/time_util.h"
#include "../common/logger.h"

namespace nr {

SnapshotResult Snapshot::take(const std::string& pool_name,
                              const std::string& tag,
                              const std::string& out_dir) {
    SnapshotResult r;
    uint64_t t0 = now_ms();
    r.path = out_dir + "/snap_" + tag + ".dat";
    // TODO: iterate tier_engine index, freeze DRAM slab via COW, stream to file.
    r.bytes   = 0;
    r.objects = 0;
    r.ok      = true;
    r.elapsed_ms = now_ms() - t0;
    NR_INFO("snapshot: pool=%s path=%s objects=%lu bytes=%lu cost=%lums",
            pool_name.c_str(), r.path.c_str(),
            (unsigned long)r.objects, (unsigned long)r.bytes,
            (unsigned long)r.elapsed_ms);
    return r;
}

} // namespace nr
