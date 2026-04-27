#pragma once
#include <cstdint>
#include <cstddef>
#include <string>
#include <vector>
#include <memory>
#include <infiniband/verbs.h>

namespace nr {

// Forward decl
struct Mr;

struct RdmaConfig {
    std::string dev_name   = "mlx5_0";   // <RDMA_DEV>
    uint8_t     gid_index  = 3;          // <GID_IDX>
    int         num_qp     = 8;
    int         sq_depth   = 1024;
    int         rq_depth   = 1024;
    int         cq_depth   = 4096;
    int         max_inline = 256;
    int         max_sge    = 4;
    bool        use_srq    = true;
};

struct MrHandle {
    void*     addr   = nullptr;
    size_t    length = 0;
    uint32_t  lkey   = 0;
    uint32_t  rkey   = 0;
    struct ibv_mr* mr = nullptr;
};

struct PeerEndpoint {
    // Exchanged via control QP during handshake.
    uint64_t  remote_addr = 0;
    uint32_t  rkey        = 0;
    size_t    length      = 0;
    uint32_t  qp_num      = 0;
    union ibv_gid gid{};
    uint16_t  lid         = 0;
    uint8_t   gid_index   = 0;
};

class RdmaCore {
public:
    RdmaCore();
    ~RdmaCore();

    bool init(const RdmaConfig& cfg);

    // Register a memory region for local + remote RDMA access.
    // Returns filled MrHandle; lifecycle managed by RdmaCore.
    MrHandle reg_mr(void* addr, size_t len);
    void     dereg_mr(MrHandle& h);

    // ---- W2: connection management ----
    // Local info needed by OOB handshake.
    uint32_t       local_qpn(int qp_idx) const;
    uint16_t       local_lid() const;
    union ibv_gid  local_gid() const;
    uint8_t        local_gid_index() const;

    // Transition one QP: INIT -> RTR -> RTS using the exchanged peer info.
    // `peer_qpn/peer_lid/peer_gid` come from OOB exchange.
    bool connect_qp(int qp_idx,
                    uint32_t peer_qpn, uint16_t peer_lid,
                    const union ibv_gid& peer_gid,
                    uint8_t peer_gid_index);

    // Post a plain RECV on the given QP for subsequent SEND receive.
    int post_recv(int qp_idx, void* buf, size_t len, uint32_t lkey,
                  uint64_t wr_id);
    // Post a plain (non-inline) SEND.
    int post_send(int qp_idx, const void* buf, size_t len, uint32_t lkey,
                  uint64_t wr_id, bool signaled);

    // Post operations on a specific QP index [0, num_qp).
    int post_write(int qp_idx, const void* buf, size_t len, uint32_t lkey,
                   uint64_t remote_addr, uint32_t rkey,
                   uint32_t imm, uint64_t wr_id, bool signaled);
    int post_read (int qp_idx, void* buf, size_t len, uint32_t lkey,
                   uint64_t remote_addr, uint32_t rkey, uint64_t wr_id);
    int post_send_inline(int qp_idx, const void* buf, size_t len,
                         uint64_t wr_id, bool signaled);

    // Chain post: caller prepares the wr_list; returns bad_wr on failure.
    int post_send_batch(int qp_idx, ibv_send_wr* wr_list, ibv_send_wr** bad);

    // Collect completions. `out` capacity must be >= max.
    int poll_cq(int cq_idx, ibv_wc* out, int max);

    // Accessors
    int num_qp()  const;
    int num_cq()  const;
    struct ibv_pd* pd() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace nr
