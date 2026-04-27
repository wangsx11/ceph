#include "object_router.h"

namespace nr {

RouteDecision ObjectRouter::route(const std::string& key) const {
    RouteDecision d;
    if (ring_.empty()) {
        d.primary = self_id_;
        d.local_is_primary = true;
        return d;
    }
    d.primary = ring_.locate(key);
    d.local_is_primary = (d.primary == self_id_);
    // For 2-node setup: replica is the other node.
    // We pick the "next different node" by hashing key+"$r".
    if (replica_cnt_ >= 2) {
        std::string rk = std::string(key) + "$r";
        const std::string& r = ring_.locate(rk);
        d.replica = (r == d.primary) ? std::string() : r;
    }
    return d;
}

} // namespace nr
