#pragma once
#include <cstdint>

namespace nr {

// Discrete-event simulation engine: one instance per data-plane process.
//
// Models an N-entity, M-event workload where each entity owns a configurable
// payload (default 1KB) and every event updates both numeric state and the
// entity payload. Matches docs/性能要求.md row #8: 100k 1KB entities,
// 1M events, >=1x realtime.
//
// ----- Semantics of the numbers reported -----
// wall_s         : actual CPU wall-clock time to execute all events.
// sim_s          : simulated wall-clock time = events * step_us / 1e6.
//                  i.e., if every event corresponds to `step_us` us of
//                  simulated time, sim_s is how long the scenario would
//                  take in real time to play out.
// speedup        : sim_s / wall_s. speedup > 1 means we finished the
//                  scenario faster than realtime.
// events_per_sec : raw compute throughput.
//
// `stress` controls how much per-event work we perform (number of LCG
// iterations). With stress=1 the loop body is ~5 ns on modern x86 and the
// reported speedup gets dominated by the step_us constant. Setting
// stress=32 gives each event ~150 ns of pure arithmetic which makes the
// throughput representative of real discrete-event workloads (particle,
// Monte-Carlo, queueing).
class SimEngine {
public:
    struct Config {
        uint32_t entities = 100000;     // default: spec row #8 target
        uint32_t entity_size = 1024;     // bytes per simulated entity
        uint64_t events   = 1000000;
        uint32_t step_us  = 10;         // simulated us per event
        uint32_t threads  = 4;          // parallel workers
        uint32_t stress   = 32;         // per-event inner iterations
        // Sampling rate for the in-run SimCapture sink. One event out of
        // every `capture_every_n` pushes an ObjectAttr record (and
        // alternating InteractionEvent records every other sample) into
        // SimCapture::instance(). Set to 0 to disable capture entirely
        // (useful for clean speedup measurements); the default 256 adds
        // <0.5% overhead at stress=32.
        uint32_t capture_every_n = 256;
    };
    struct Report {
        uint32_t entities       = 0;
        uint32_t entity_size    = 0;
        uint64_t entity_bytes   = 0;
        uint64_t events         = 0;
        double   wall_s         = 0.0;
        double   sim_s          = 0.0;
        double   speedup        = 0.0;   // sim_s / wall_s
        double   events_per_sec = 0.0;
        uint64_t last_state_sum = 0;     // checksum to defeat compiler opt
    };
    bool         init(const Config& cfg);
    Report       run();                  // blocking; returns once events exhausted
    double       speedup() const { return last_report_.speedup; }
    const Report& last_report() const { return last_report_; }
    void         reset() { last_report_ = Report{}; }

private:
    Config  cfg_{};
    Report  last_report_{};
};

} // namespace nr
