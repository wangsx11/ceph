#pragma once
#include <cstdint>

namespace nr {

// Discrete-event simulation engine: one instance per data-plane process.
class SimEngine {
public:
    struct Config {
        uint32_t entities = 25000;      // per process
        uint64_t events   = 250000;     // per process
        uint32_t step_us  = 1000;       // simulation tick
    };
    bool  init(const Config& cfg);
    void  run();
    double speedup() const { return speedup_; }

private:
    Config  cfg_{};
    double  speedup_ = 0.0;
};

} // namespace nr
