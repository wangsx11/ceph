#pragma once
#include <cstdint>

namespace nr {

// Discrete-event simulation engine: one instance per data-plane process.
//
// Models an N-entity, M-event workload where every event updates an
// entity's numeric state, validates it, and feeds the result back into
// the event pool. Matches docs/自研实施清单.md §7 row #8 requirement:
// "100 万 events across 10 万 entities >= 1x realtime".
//
// Realtime baseline: 1 simulated event takes `step_us` microseconds of
// simulated time. A wall-clock 1x run means we finished
// `events * step_us` us of simulated time in the same wall-clock budget.
class SimEngine {
public:
    struct Config {
        uint32_t entities = 100000;     // default: spec row #8 target
        uint64_t events   = 1000000;
        uint32_t step_us  = 10;         // 10us per simulated tick
        uint32_t threads  = 4;          // parallel workers
    };
    struct Report {
        uint32_t entities       = 0;
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
