#include "rdma_core.h"
#include "../common/logger.h"

#include <cstring>
#include <cstdlib>
#include <mutex>
#include <memory>

namespace nr {

struct RdmaCore::Impl {
    RdmaConfig              cfg;
    struct ibv_context*     ctx  = nullptr;
    struct ibv_pd*          pd   = nullptr;
    struct ibv_srq*         srq  = nullptr;
    std::vector<ibv_cq*>    cqs;   // one per QP group
    std::vector<ibv_qp*>    qps;
    // Per-QP post/poll mutexes. ibverbs SQ is NOT thread-safe: concurrent
    // ibv_post_send on the same QP must be externally serialized. Likewise
    // ibv_poll_cq is not safe to call from multiple threads on the same CQ.
    // We use unique_ptr<mutex> so the container is stable even after resize.
    std::vector<std::unique_ptr<std::mutex>> post_mu;
    std::vector<std::unique_ptr<std::mutex>> poll_mu;
    union ibv_gid           local_gid{};

    bool open_device();
    bool create_pd_cqs_qps();
    bool modify_qp_init(ibv_qp* qp);
    void cleanup();
};

RdmaCore::RdmaCore() : impl_(std::make_unique<Impl>()) {}
RdmaCore::~RdmaCore() { if (impl_) impl_->cleanup(); }

int RdmaCore::num_qp() const { return (int)impl_->qps.size(); }
int RdmaCore::num_cq() const { return (int)impl_->cqs.size(); }
struct ibv_pd* RdmaCore::pd() const { return impl_->pd; }

// ------------------------------------------------------------------
bool RdmaCore::Impl::open_device() {
    int n = 0;
    ibv_device** list = ibv_get_device_list(&n);
    if (!list || n == 0) {
        NR_ERROR("no RDMA devices found");
        return false;
    }
    ibv_device* dev = nullptr;
    for (int i = 0; i < n; ++i) {
        if (cfg.dev_name == ibv_get_device_name(list[i])) {
            dev = list[i]; break;
        }
    }
    if (!dev) {
        NR_ERROR("RDMA device '%s' not found", cfg.dev_name.c_str());
        ibv_free_device_list(list);
        return false;
    }
    ctx = ibv_open_device(dev);
    ibv_free_device_list(list);
    if (!ctx) { NR_ERROR("ibv_open_device failed"); return false; }

    if (ibv_query_gid(ctx, 1, cfg.gid_index, &local_gid)) {
        NR_ERROR("ibv_query_gid(port=1, idx=%d) failed", cfg.gid_index);
        return false;
    }
    NR_INFO("RDMA device '%s' opened, gid_idx=%u", cfg.dev_name.c_str(),
            cfg.gid_index);
    return true;
}

bool RdmaCore::Impl::create_pd_cqs_qps() {
    pd = ibv_alloc_pd(ctx);
    if (!pd) { NR_ERROR("ibv_alloc_pd failed"); return false; }

    // One CQ per QP for simplicity; can share later for efficiency.
    cqs.resize(cfg.num_qp, nullptr);
    qps.resize(cfg.num_qp, nullptr);
    post_mu.clear();
    poll_mu.clear();
    post_mu.reserve(cfg.num_qp);
    poll_mu.reserve(cfg.num_qp);
    for (int i = 0; i < cfg.num_qp; ++i) {
        post_mu.emplace_back(new std::mutex());
        poll_mu.emplace_back(new std::mutex());
        cqs[i] = ibv_create_cq(ctx, cfg.cq_depth, nullptr, nullptr, 0);
        if (!cqs[i]) { NR_ERROR("ibv_create_cq failed"); return false; }

        ibv_qp_init_attr attr{};
        attr.send_cq = cqs[i];
        attr.recv_cq = cqs[i];
        attr.qp_type = IBV_QPT_RC;
        attr.cap.max_send_wr  = cfg.sq_depth;
        attr.cap.max_recv_wr  = cfg.rq_depth;
        attr.cap.max_send_sge = cfg.max_sge;
        attr.cap.max_recv_sge = cfg.max_sge;
        attr.cap.max_inline_data = cfg.max_inline;
        attr.sq_sig_all = 0; // we will set signaled flag per WR
        qps[i] = ibv_create_qp(pd, &attr);
        if (!qps[i]) {
            NR_ERROR("ibv_create_qp[%d] failed", i);
            return false;
        }
        if (!modify_qp_init(qps[i])) return false;
    }
    NR_INFO("created %d QPs, sq_depth=%d, cq_depth=%d, inline=%d",
            cfg.num_qp, cfg.sq_depth, cfg.cq_depth, cfg.max_inline);
    return true;
}

bool RdmaCore::Impl::modify_qp_init(ibv_qp* qp) {
    ibv_qp_attr attr{};
    attr.qp_state        = IBV_QPS_INIT;
    attr.pkey_index      = 0;
    attr.port_num        = 1;
    attr.qp_access_flags = IBV_ACCESS_LOCAL_WRITE |
                           IBV_ACCESS_REMOTE_READ |
                           IBV_ACCESS_REMOTE_WRITE |
                           IBV_ACCESS_REMOTE_ATOMIC;
    int flags = IBV_QP_STATE | IBV_QP_PKEY_INDEX |
                IBV_QP_PORT  | IBV_QP_ACCESS_FLAGS;
    if (ibv_modify_qp(qp, &attr, flags)) {
        NR_ERROR("modify_qp(INIT) failed");
        return false;
    }
    return true;
}

void RdmaCore::Impl::cleanup() {
    for (auto* qp : qps) if (qp) ibv_destroy_qp(qp);
    qps.clear();
    for (auto* cq : cqs) if (cq) ibv_destroy_cq(cq);
    cqs.clear();
    if (pd)  { ibv_dealloc_pd(pd); pd = nullptr; }
    if (ctx) { ibv_close_device(ctx); ctx = nullptr; }
}

// ------------------------------------------------------------------
bool RdmaCore::init(const RdmaConfig& cfg) {
    impl_->cfg = cfg;
    if (!impl_->open_device()) return false;
    if (!impl_->create_pd_cqs_qps()) return false;
    return true;
}

MrHandle RdmaCore::reg_mr(void* addr, size_t len) {
    MrHandle h{};
    int access = IBV_ACCESS_LOCAL_WRITE |
                 IBV_ACCESS_REMOTE_READ |
                 IBV_ACCESS_REMOTE_WRITE;
    h.mr = ibv_reg_mr(impl_->pd, addr, len, access);
    if (!h.mr) {
        NR_ERROR("ibv_reg_mr(%p, %zu) failed", addr, len);
        return h;
    }
    h.addr = addr; h.length = len;
    h.lkey = h.mr->lkey; h.rkey = h.mr->rkey;
    return h;
}

void RdmaCore::dereg_mr(MrHandle& h) {
    if (h.mr) { ibv_dereg_mr(h.mr); h.mr = nullptr; }
}

int RdmaCore::post_write(int qp_idx, const void* buf, size_t len, uint32_t lkey,
                         uint64_t remote_addr, uint32_t rkey,
                         uint32_t imm, uint64_t wr_id, bool signaled)
{
    ibv_sge sge{(uint64_t)buf, (uint32_t)len, lkey};
    ibv_send_wr wr{};
    wr.wr_id      = wr_id;
    wr.sg_list    = &sge;
    wr.num_sge    = 1;
    wr.opcode     = imm ? IBV_WR_RDMA_WRITE_WITH_IMM : IBV_WR_RDMA_WRITE;
    wr.send_flags = (signaled ? IBV_SEND_SIGNALED : 0) |
                    ((len <= (size_t)impl_->cfg.max_inline) ? IBV_SEND_INLINE : 0);
    wr.imm_data   = imm;
    wr.wr.rdma.remote_addr = remote_addr;
    wr.wr.rdma.rkey        = rkey;
    ibv_send_wr* bad = nullptr;
    std::lock_guard<std::mutex> lk(*impl_->post_mu[qp_idx]);
    return ibv_post_send(impl_->qps[qp_idx], &wr, &bad);
}

int RdmaCore::post_read(int qp_idx, void* buf, size_t len, uint32_t lkey,
                        uint64_t remote_addr, uint32_t rkey, uint64_t wr_id)
{
    ibv_sge sge{(uint64_t)buf, (uint32_t)len, lkey};
    ibv_send_wr wr{};
    wr.wr_id      = wr_id;
    wr.sg_list    = &sge;
    wr.num_sge    = 1;
    wr.opcode     = IBV_WR_RDMA_READ;
    wr.send_flags = IBV_SEND_SIGNALED;
    wr.wr.rdma.remote_addr = remote_addr;
    wr.wr.rdma.rkey        = rkey;
    ibv_send_wr* bad = nullptr;
    std::lock_guard<std::mutex> lk(*impl_->post_mu[qp_idx]);
    return ibv_post_send(impl_->qps[qp_idx], &wr, &bad);
}

int RdmaCore::post_send_inline(int qp_idx, const void* buf, size_t len,
                               uint64_t wr_id, bool signaled)
{
    ibv_sge sge{(uint64_t)buf, (uint32_t)len, 0};
    ibv_send_wr wr{};
    wr.wr_id      = wr_id;
    wr.sg_list    = &sge;
    wr.num_sge    = 1;
    wr.opcode     = IBV_WR_SEND;
    wr.send_flags = IBV_SEND_INLINE | (signaled ? IBV_SEND_SIGNALED : 0);
    ibv_send_wr* bad = nullptr;
    std::lock_guard<std::mutex> lk(*impl_->post_mu[qp_idx]);
    return ibv_post_send(impl_->qps[qp_idx], &wr, &bad);
}

int RdmaCore::post_recv(int qp_idx, void* buf, size_t len, uint32_t lkey,
                        uint64_t wr_id)
{
    ibv_sge sge{(uint64_t)buf, (uint32_t)len, lkey};
    ibv_recv_wr wr{};
    wr.wr_id   = wr_id;
    wr.sg_list = &sge;
    wr.num_sge = 1;
    ibv_recv_wr* bad = nullptr;
    std::lock_guard<std::mutex> lk(*impl_->post_mu[qp_idx]);
    return ibv_post_recv(impl_->qps[qp_idx], &wr, &bad);
}

int RdmaCore::post_send(int qp_idx, const void* buf, size_t len, uint32_t lkey,
                        uint64_t wr_id, bool signaled)
{
    ibv_sge sge{(uint64_t)buf, (uint32_t)len, lkey};
    ibv_send_wr wr{};
    wr.wr_id      = wr_id;
    wr.sg_list    = &sge;
    wr.num_sge    = 1;
    wr.opcode     = IBV_WR_SEND;
    wr.send_flags = signaled ? IBV_SEND_SIGNALED : 0;
    ibv_send_wr* bad = nullptr;
    std::lock_guard<std::mutex> lk(*impl_->post_mu[qp_idx]);
    return ibv_post_send(impl_->qps[qp_idx], &wr, &bad);
}

int RdmaCore::post_send_batch(int qp_idx, ibv_send_wr* wr_list, ibv_send_wr** bad)
{
    std::lock_guard<std::mutex> lk(*impl_->post_mu[qp_idx]);
    return ibv_post_send(impl_->qps[qp_idx], wr_list, bad);
}

int RdmaCore::poll_cq(int cq_idx, ibv_wc* out, int max)
{
    std::lock_guard<std::mutex> lk(*impl_->poll_mu[cq_idx]);
    return ibv_poll_cq(impl_->cqs[cq_idx], max, out);
}

uint32_t RdmaCore::local_qpn(int qp_idx) const {
    return impl_->qps[qp_idx]->qp_num;
}

uint16_t RdmaCore::local_lid() const {
    ibv_port_attr pa{};
    if (ibv_query_port(impl_->ctx, 1, &pa) != 0) return 0;
    return pa.lid;
}

union ibv_gid RdmaCore::local_gid() const {
    return impl_->local_gid;
}

uint8_t RdmaCore::local_gid_index() const {
    return impl_->cfg.gid_index;
}

bool RdmaCore::reset_qp(int qp_idx)
{
    if (qp_idx < 0 || qp_idx >= impl_->cfg.num_qp) {
        NR_ERROR("reset_qp: bad qp_idx=%d", qp_idx);
        return false;
    }
    auto* qp = impl_->qps[qp_idx];

    // Step 1: any state -> RESET.
    ibv_qp_attr r{};
    r.qp_state = IBV_QPS_RESET;
    if (ibv_modify_qp(qp, &r, IBV_QP_STATE)) {
        NR_ERROR("reset_qp(%d): modify -> RESET failed", qp_idx);
        return false;
    }

    // Step 2: RESET -> INIT (mirrors modify_qp_init's attrs).
    ibv_qp_attr a{};
    a.qp_state        = IBV_QPS_INIT;
    a.pkey_index      = 0;
    a.port_num        = 1;
    a.qp_access_flags = IBV_ACCESS_LOCAL_WRITE |
                        IBV_ACCESS_REMOTE_WRITE |
                        IBV_ACCESS_REMOTE_READ |
                        IBV_ACCESS_REMOTE_ATOMIC;
    int flags = IBV_QP_STATE | IBV_QP_PKEY_INDEX |
                IBV_QP_PORT | IBV_QP_ACCESS_FLAGS;
    if (ibv_modify_qp(qp, &a, flags)) {
        NR_ERROR("reset_qp(%d): modify -> INIT failed", qp_idx);
        return false;
    }
    NR_INFO("reset_qp(%d): now in INIT, caller should connect_qp() next",
            qp_idx);
    return true;
}

bool RdmaCore::connect_qp(int qp_idx,
                          uint32_t peer_qpn, uint16_t peer_lid,
                          const union ibv_gid& peer_gid,
                          uint8_t peer_gid_index)
{
    auto* qp = impl_->qps[qp_idx];

    // ---------- INIT -> RTR ----------
    ibv_qp_attr attr{};
    attr.qp_state           = IBV_QPS_RTR;
    attr.path_mtu           = IBV_MTU_1024;
    attr.dest_qp_num        = peer_qpn;
    attr.rq_psn             = 0;
    attr.max_dest_rd_atomic = 16;
    attr.min_rnr_timer      = 12;

    attr.ah_attr.is_global     = 1;              // RoCE v2 needs GRH
    attr.ah_attr.dlid          = peer_lid;
    attr.ah_attr.sl            = 0;
    attr.ah_attr.src_path_bits = 0;
    attr.ah_attr.port_num      = 1;
    attr.ah_attr.grh.dgid            = peer_gid;
    attr.ah_attr.grh.sgid_index      = impl_->cfg.gid_index;
    attr.ah_attr.grh.hop_limit       = 64;
    attr.ah_attr.grh.traffic_class   = impl_->cfg.traffic_class;
    attr.ah_attr.grh.flow_label      = 0;
    (void)peer_gid_index;  // caller provides; we use our own sgid_index.

    int flags = IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU |
                IBV_QP_DEST_QPN | IBV_QP_RQ_PSN |
                IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER;
    if (ibv_modify_qp(qp, &attr, flags)) {
        NR_ERROR("modify_qp(RTR) qp=%d failed", qp_idx);
        return false;
    }

    // ---------- RTR -> RTS ----------
    ibv_qp_attr rts{};
    rts.qp_state      = IBV_QPS_RTS;
    rts.timeout       = 14;
    rts.retry_cnt     = 7;
    rts.rnr_retry     = 7;
    rts.sq_psn        = 0;
    rts.max_rd_atomic = 16;
    int rflags = IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT |
                 IBV_QP_RNR_RETRY | IBV_QP_SQ_PSN | IBV_QP_MAX_QP_RD_ATOMIC;
    if (ibv_modify_qp(qp, &rts, rflags)) {
        NR_ERROR("modify_qp(RTS) qp=%d failed", qp_idx);
        return false;
    }
    NR_INFO("qp[%d] connected: peer_qpn=0x%x lid=%u", qp_idx, peer_qpn, peer_lid);
    return true;
}

} // namespace nr
