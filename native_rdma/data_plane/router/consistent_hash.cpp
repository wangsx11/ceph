#include "consistent_hash.h"
#include <algorithm>

namespace nr {

// FNV-1a 64 – cheap and good enough for routing.
static uint64_t fnv1a_64(const void* data, size_t len) {
    const uint8_t* p = static_cast<const uint8_t*>(data);
    uint64_t h = 1469598103934665603ULL;
    for (size_t i = 0; i < len; ++i) {
        h ^= p[i];
        h *= 1099511628211ULL;
    }
    return h;
}

ConsistentHash::ConsistentHash(int vnodes_per_node) : vnodes_(vnodes_per_node) {}

void ConsistentHash::add_node(const std::string& node_id) {
    for (int i = 0; i < vnodes_; ++i) {
        std::string k = node_id + "#" + std::to_string(i);
        Entry e{fnv1a_64(k.data(), k.size()), node_id};
        ring_.push_back(e);
    }
    std::sort(ring_.begin(), ring_.end(),
              [](const Entry& a, const Entry& b) { return a.hash < b.hash; });
}

void ConsistentHash::remove_node(const std::string& node_id) {
    ring_.erase(std::remove_if(ring_.begin(), ring_.end(),
                [&](const Entry& e) { return e.node_id == node_id; }),
                ring_.end());
}

const std::string& ConsistentHash::locate(std::string_view key) const {
    static const std::string EMPTY;
    if (ring_.empty()) return EMPTY;
    uint64_t h = fnv1a_64(key.data(), key.size());
    auto it = std::lower_bound(ring_.begin(), ring_.end(), h,
        [](const Entry& e, uint64_t v) { return e.hash < v; });
    if (it == ring_.end()) it = ring_.begin();
    return it->node_id;
}

} // namespace nr
