#pragma once
#include <string>
#include <string_view>
#include <deque>
#include <unordered_map>
#include <mutex>
#include <cstdint>
#include <vector>

namespace nr {

// Dual-strategy prefetch predictor:
//   1) Sequential stride: when the last N (=4) accesses all share the same
//      numeric stride (e.g. keys "obj_10", "obj_11", "obj_12", "obj_13"),
//      predict the next 8 keys along the same stride.
//   2) Markov-1: build a transition map {key -> most frequent next key}.
//
// Thread-safe via an internal mutex. Lookup cost is O(1). Memory bounded by
// the max_transitions cap; evicts oldest entries when exceeded.
class Prefetcher {
public:
    struct Config {
        int    stride_window  = 4;     // #consecutive accesses needed to lock a stride
        int    prefetch_depth = 8;     // # future keys to return per hit
        size_t max_transitions = 100000; // upper bound on Markov table size
    };
    struct Stats {
        uint64_t hits_stride  = 0;
        uint64_t hits_markov  = 0;
        uint64_t total_access = 0;
    };

    void init(const Config& cfg = {}) {
        std::lock_guard<std::mutex> lk(mu_);
        cfg_ = cfg;
    }

    // Record an access (call before/after each real GET).
    void on_access(std::string_view key);

    // Return a list of predicted next keys (may be empty).
    std::vector<std::string> predict(std::string_view key) const;

    // For simple yes/no queries.
    bool should_prefetch(std::string_view key) const {
        return !predict(key).empty();
    }

    Stats stats() const {
        std::lock_guard<std::mutex> lk(mu_);
        return s_;
    }

private:
    // Try to parse an integer suffix from a key like "obj_42" -> {"obj_", 42}.
    // Returns false if no trailing digits.
    static bool split_numeric(std::string_view key,
                              std::string* prefix, long long* num);

    Config       cfg_{};
    mutable std::mutex          mu_;
    std::deque<std::string>     history_;    // last N keys
    std::unordered_map<std::string, std::unordered_map<std::string, uint32_t>>
                                transitions_;
    std::string  last_key_;
    mutable Stats               s_;
};

} // namespace nr
