#pragma once
#include <cstdint>
#include <cstddef>
#include <string>
#include <functional>

namespace nr {

// Thin wrapper around io_uring with two priority classes (FG/BG).
// When NR_USE_IO_URING is undefined, falls back to pread/pwrite.
class IoScheduler {
public:
    enum class Prio { FG, BG };

    struct Config {
        std::string fg_path;
        std::string bg_path;
        int sq_depth    = 1024;
        bool sq_poll_fg = true;     // IORING_SETUP_SQPOLL for FG
    };

    using OnDone = std::function<void(int rc)>;

    bool init(const Config& cfg);
    void shutdown();

    // Async write; callback invoked when CQ reaps completion.
    int async_write(Prio p, const void* buf, size_t len, uint64_t offset,
                    OnDone cb);
    int async_read (Prio p, void* buf,       size_t len, uint64_t offset,
                    OnDone cb);

    // Blocking helper (used by cold-path snapshot / migration).
    int sync_write(Prio p, const void* buf, size_t len, uint64_t offset);
    int sync_read (Prio p, void* buf,       size_t len, uint64_t offset);
};

} // namespace nr
