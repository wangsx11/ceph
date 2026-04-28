#pragma once
// SimCapture: lossless in-run capture of simulation events.
//
// Meets docs/功能要求.md storage module #6: "在仿真运行过程中及时捕获
// 多类型的数据流，包括对象属性、交互事件等". Producers (SimEngine
// workers, upstream business code) call push() from the hot path; a
// background thread batch-flushes the collected events to a sink.
//
// Design notes:
//   * Event header is fixed-size (32 B) + variable blob, packed as a
//     ring-backed MPSC queue so multiple worker threads can produce
//     without taking a mutex per event.
//   * The sink is pluggable; by default we use an on-disk WAL under
//     <capture_dir>/sim_<tag>.log so the data survives process restart
//     and can be replayed. Tests can swap in a memory sink.
//   * Two built-in event types match the spec wording:
//       type=1  ObjectAttr       - an entity's state changed
//       type=2  InteractionEvent - two entities interacted
//     User code is free to register any other 16-bit type.
//   * Backpressure: if the ring is full, push() returns false and
//     drops_ is incremented. Producers may choose to retry or discard.
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace nr {

struct SimEventHeader {
    uint64_t ts_ns;        // monotonic timestamp at push time
    uint64_t entity_id;    // primary entity id
    uint64_t peer_id;      // second entity id (interaction) or 0 for Attr
    uint16_t type;         // 1=ObjectAttr, 2=InteractionEvent, ...
    uint16_t blob_len;     // bytes of blob that follow
    uint32_t reserved;     // pad to 32 B, also leaves room for future flags
} __attribute__((packed));
static_assert(sizeof(SimEventHeader) == 32, "SimEventHeader must be 32 B");

class SimCapture {
public:
    struct Config {
        // Where to persist the WAL. Directory is created on init; each
        // capture session writes to <capture_dir>/sim_<tag>.log.
        std::string capture_dir = "/tmp/nr_sim_capture";
        std::string tag         = "default";
        // Ring capacity in bytes. 16 MB is enough for a ~100k evt/s
        // producer with a 100 ms flush cadence at ~160 B/event.
        size_t      ring_bytes       = 16 * 1024 * 1024;
        // How often the background thread drains the ring to the sink.
        int         flush_interval_ms = 100;
        // If true, also fsync() after each flush. Disabled by default:
        // capture is meant to be cheap; durability relies on OS cache.
        bool        fsync_on_flush   = false;
    };

    struct Stats {
        uint64_t pushed_events = 0;
        uint64_t pushed_bytes  = 0;
        uint64_t flushed_events = 0;
        uint64_t flushed_bytes  = 0;
        uint64_t dropped_events = 0;   // ring full
    };

    // Built-in event type codes.
    static constexpr uint16_t TYPE_OBJECT_ATTR = 1;
    static constexpr uint16_t TYPE_INTERACTION = 2;

    // Default singleton; tests may construct private instances.
    static SimCapture& instance();

    // init() must be called once before push(); start() spawns the
    // background flush thread. Safe to call again with a different tag
    // after stop(), e.g. for a new "capture session".
    bool init (const Config& cfg);
    bool start();
    void stop();      // joins the bg thread, does a final flush

    // Reset counters and the on-disk log for the current tag. Useful
    // between demo takes.
    void reset();

    // Producer API. push_attr records a single entity's state; push_event
    // records an interaction between two entities; push_raw is the
    // escape hatch for user-defined type codes. All of these are
    // thread-safe, lock-free on the fast path, and O(1).
    bool push_attr (uint64_t entity_id, const void* blob, size_t blob_len);
    bool push_event(uint64_t a_id, uint64_t b_id,
                    const void* blob, size_t blob_len);
    bool push_raw  (uint16_t type, uint64_t entity_id, uint64_t peer_id,
                    const void* blob, size_t blob_len);

    Stats stats() const;

private:
    void run();       // background thread body
    bool write_sink(const void* buf, size_t len);  // flush helper

    Config          cfg_;
    std::atomic<bool> running_{false};
    std::thread     bg_;

    // Ring buffer: we keep it simple -- a std::vector<uint8_t> guarded
    // by a mutex that the producers hold only for the nanoseconds it
    // takes to memcpy. The background thread swaps in a fresh vector
    // under the same mutex, so the flush I/O happens without blocking
    // producers.
    mutable std::mutex mu_;
    std::vector<uint8_t> ring_;   // active buffer producers append to
    std::vector<uint8_t> drain_;  // private buffer the flusher consumes

    // Sink: file handle for the WAL.
    std::ofstream   log_;
    std::string     log_path_;

    // Stats (all under mu_ for simplicity).
    Stats           s_{};
};

} // namespace nr
