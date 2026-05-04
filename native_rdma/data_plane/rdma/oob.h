#pragma once
#include "rdma_core.h"
#include "tcp_fallback.h"
#include <cstdint>
#include <string>
#include <vector>
#include <infiniband/verbs.h>

namespace nr {

// Peer endpoint information learned from the OOB (TCP) handshake.
struct RemoteEndpoint {
    uint64_t      slab_base    = 0;      // peer slab VA (for RDMA write/read)
    uint64_t      slab_len     = 0;
    uint32_t      slab_rkey    = 0;
    bool          gpu_enabled  = false;
    uint64_t      gpu_base     = 0;      // peer GPU VA for GPUDirect RDMA
    uint64_t      gpu_len      = 0;
    uint32_t      gpu_rkey     = 0;
    uint16_t      lid          = 0;
    uint8_t       gid_index    = 0;
    union ibv_gid gid{};
    std::vector<uint32_t> qpns;          // peer qpn per qp index
};

// Perform TCP-based handshake exchanging: lid, gid, gid_index, num_qp, all qpns,
// and remote slab (base, len, rkey). On success, all local QPs are already
// transitioned INIT -> RTR -> RTS. `is_listener=true` means this side binds and
// accepts; the other side connects.
bool oob_handshake(RdmaCore& core,
                   const std::string& self_ip,
                   const std::string& peer_ip,
                   uint16_t oob_port,
                   bool is_listener,
                   uint64_t local_slab_base,
                   uint64_t local_slab_len,
                   uint32_t local_slab_rkey,
                   bool local_gpu_enabled,
                   uint64_t local_gpu_base,
                   uint64_t local_gpu_len,
                   uint32_t local_gpu_rkey,
                   RemoteEndpoint* peer);

} // namespace nr
