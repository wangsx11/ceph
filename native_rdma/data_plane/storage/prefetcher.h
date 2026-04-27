#pragma once
#include <string>
#include <string_view>

namespace nr {

// Sequential + Markov-1 prefetch detector. Stubbed.
class Prefetcher {
public:
    void on_access(std::string_view key);
    // Return true if this key is predicted as next access target.
    bool should_prefetch(std::string_view key) const;
};

} // namespace nr
