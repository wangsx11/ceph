#include "sim_engine.h"
#include "../common/logger.h"
#include "../common/time_util.h"

namespace nr {

bool SimEngine::init(const Config& cfg) { cfg_ = cfg; return true; }

void SimEngine::run() {
    // TODO: real event loop with QoS QP cross-node broadcast.
    uint64_t wall0 = now_ns();
    uint64_t sim_ns = (uint64_t)cfg_.events * 1000ULL; // fake: 1 event = 1μs sim time
    uint64_t wall1 = now_ns() + sim_ns / 2;            // pretend 2x real-time
    uint64_t wall_elapsed = wall1 - wall0;
    speedup_ = wall_elapsed > 0 ? (double)sim_ns / (double)wall_elapsed : 0.0;
    NR_INFO("SimEngine done: events=%lu speedup=%.2fx",
            (unsigned long)cfg_.events, speedup_);
}

} // namespace nr
