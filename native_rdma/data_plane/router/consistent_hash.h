#pragma once
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace nr {

// Consistent hash ring with virtual nodes. Maps key -> node_id.
class ConsistentHash {
public:
    explicit ConsistentHash(int vnodes_per_node = 160);

    void add_node(const std::string& node_id);
    void remove_node(const std::string& node_id);

    const std::string& locate(std::string_view key) const;
    bool empty() const { return ring_.empty(); }

private:
    int vnodes_;
    struct Entry { uint64_t hash; std::string node_id; };
    std::vector<Entry> ring_;  // sorted by hash
};

} // namespace nr
