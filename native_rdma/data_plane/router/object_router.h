#pragma once
#include "consistent_hash.h"
#include <string>

namespace nr {

struct RouteDecision {
    std::string primary;
    std::string replica;   // empty if replica count == 1
    bool        local_is_primary = false;
};

class ObjectRouter {
public:
    void set_self_id(const std::string& id) { self_id_ = id; }
    void add_node(const std::string& node_id) { ring_.add_node(node_id); }
    void set_replica_count(int rc) { replica_cnt_ = rc; }

    RouteDecision route(const std::string& key) const;

private:
    std::string     self_id_;
    ConsistentHash  ring_;
    int             replica_cnt_ = 2;
};

} // namespace nr
