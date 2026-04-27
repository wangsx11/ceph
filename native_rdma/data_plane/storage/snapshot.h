#pragma once
#include <cstdint>
#include <string>

namespace nr {

struct SnapshotResult {
    std::string path;
    uint64_t    bytes       = 0;
    uint64_t    objects     = 0;
    uint64_t    elapsed_ms  = 0;
    bool        ok          = false;
};

class Snapshot {
public:
    // Take a COW snapshot of the named pool into `out_dir`.
    static SnapshotResult take(const std::string& pool_name,
                               const std::string& tag,
                               const std::string& out_dir);
};

} // namespace nr
