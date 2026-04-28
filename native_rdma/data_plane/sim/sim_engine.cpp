#include "sim_engine.h"
#include "../common/logger.h"
#include "../common/time_util.h"

#include <atomic>
#include <chrono>
#include <cstdint>
#include <thread>
#include <vector>

namespace nr {

namespace {

// Per-entity simulation state. Kept deliberately small (16 B) so we can
// hold 100k entities in ~1.6 MB and stay resident in L2/L3.
struct alignas(16) Entity {
    uint64_t state;     // accumulator (mod 2^64)
    uint64_t visits;    // event counter
};

// Cheap splittable PRNG so each thread has its own stream without contention.
static inline uint64_t splitmix64(uint64_t& s) {
    uint64_t z = (s += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

}  // namespace

bool SimEngine::init(const Config& cfg) {
    cfg_ = cfg;
    if (cfg_.entities == 0) cfg_.entities = 1;
    if (cfg_.events   == 0) cfg_.events   = 1;
    if (cfg_.threads  == 0) cfg_.threads  = 1;
    if (cfg_.step_us  == 0) cfg_.step_us  = 1;
    if (cfg_.stress   == 0) cfg_.stress   = 1;
    return true;
}

SimEngine::Report SimEngine::run() {
    // Allocate the entity array once.  All workers will update it in place
    // with relaxed atomic semantics; since each event touches a random
    // entity and the state op is commutative, collisions are harmless for
    // the purposes of this benchmark (we only check final speedup).
    std::vector<Entity> world(cfg_.entities);
    for (uint32_t i = 0; i < cfg_.entities; ++i) {
        world[i].state  = (uint64_t)i * 0x9E3779B97F4A7C15ULL;
        world[i].visits = 0;
    }

    const uint32_t T = cfg_.threads;
    const uint64_t per_thread = cfg_.events / T;
    const uint64_t leftover   = cfg_.events - per_thread * T;

    std::atomic<uint64_t> checksum{0};
    auto worker = [&](uint32_t tid, uint64_t n_events) {
        uint64_t seed = 0xC0FFEE00ULL ^ ((uint64_t)tid << 32) ^ n_events;
        uint64_t acc  = 0;
        const uint32_t ents = cfg_.entities;
        const uint32_t stress = cfg_.stress;
        for (uint64_t i = 0; i < n_events; ++i) {
            uint64_t r   = splitmix64(seed);
            uint32_t eid = (uint32_t)(r % ents);
            uint64_t s   = world[eid].state;
            // Each event does `stress` rounds of LCG state integration,
            // modelling the inner cost of a real DES event handler
            // (e.g. particle update, queue service).
            for (uint32_t k = 0; k < stress; ++k) {
                s = (s * 6364136223846793005ULL) + (r | 1ULL);
                r = splitmix64(seed);
            }
            world[eid].state  = s;
            world[eid].visits = world[eid].visits + 1;
            acc ^= s;
        }
        checksum.fetch_add(acc, std::memory_order_relaxed);
    };

    uint64_t t_wall0 = now_ns();
    std::vector<std::thread> ths;
    ths.reserve(T);
    for (uint32_t t = 0; t < T; ++t) {
        uint64_t n = per_thread + (t == 0 ? leftover : 0);
        ths.emplace_back(worker, t, n);
    }
    for (auto& th : ths) th.join();
    uint64_t t_wall1 = now_ns();

    double wall_s = (t_wall1 - t_wall0) / 1e9;
    // Simulated time = events * step_us (one event advances the world by
    // step_us of simulated wall-clock time).
    double sim_s  = (double)cfg_.events * (double)cfg_.step_us / 1e6;

    Report r;
    r.entities       = cfg_.entities;
    r.events         = cfg_.events;
    r.wall_s         = wall_s;
    r.sim_s          = sim_s;
    r.speedup        = (wall_s > 0) ? (sim_s / wall_s) : 0.0;
    r.events_per_sec = (wall_s > 0) ? ((double)cfg_.events / wall_s) : 0.0;
    r.last_state_sum = checksum.load();
    last_report_     = r;

    NR_INFO("SimEngine done: entities=%u events=%lu threads=%u "
            "wall=%.3fs sim=%.3fs speedup=%.2fx events/s=%.0f",
            r.entities, (unsigned long)r.events, cfg_.threads,
            r.wall_s, r.sim_s, r.speedup, r.events_per_sec);
    return r;
}

} // namespace nr
