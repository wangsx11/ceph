#include "oob.h"
#include "../common/logger.h"
#include "../common/time_util.h"
#include <cstring>
#include <vector>
#include <thread>
#include <chrono>

namespace nr {

// Wire format (manual byte layout, host order == little endian x86 on both sides):
//   u16  lid
//   u8   gid_index
//   u8   pad
//   u32  num_qp
//   16B  gid bytes
//   u64  slab_base
//   u64  slab_len
//   u32  slab_rkey
//   u32  pad
//   u64  gpu_base
//   u64  gpu_len
//   u32  gpu_rkey
//   u8   gpu_enabled
//   u8[3] pad
//   num_qp * u32 qpn
// Total header = 72 bytes + 4 * num_qp
static constexpr size_t kOobHdrSize = 72;

static bool send_info(TcpFallback& ch, const RdmaCore& core,
                      uint64_t slab_base, uint64_t slab_len, uint32_t slab_rkey,
                      bool gpu_enabled, uint64_t gpu_base, uint64_t gpu_len,
                      uint32_t gpu_rkey)
{
    uint32_t nqp = (uint32_t)core.num_qp();
    std::vector<uint8_t> buf(kOobHdrSize + 4 * (size_t)nqp, 0);
    uint8_t* p = buf.data();

    uint16_t lid = core.local_lid();
    uint8_t  gi  = core.local_gid_index();
    std::memcpy(p + 0, &lid, 2);
    p[2] = gi; p[3] = 0;
    std::memcpy(p + 4, &nqp, 4);
    union ibv_gid g = core.local_gid();
    std::memcpy(p + 8, g.raw, 16);
    std::memcpy(p + 24, &slab_base, 8);
    std::memcpy(p + 32, &slab_len,  8);
    std::memcpy(p + 40, &slab_rkey, 4);
    // p[44..47] pad
    std::memcpy(p + 48, &gpu_base, 8);
    std::memcpy(p + 56, &gpu_len,  8);
    std::memcpy(p + 64, &gpu_rkey, 4);
    p[68] = gpu_enabled ? 1 : 0;
    // p[69..71] pad
    uint8_t* q = p + kOobHdrSize;
    for (uint32_t i = 0; i < nqp; ++i) {
        uint32_t qpn = core.local_qpn((int)i);
        std::memcpy(q + i * 4, &qpn, 4);
    }
    return ch.send_all(buf.data(), buf.size()) >= 0;
}

static bool recv_info(TcpFallback& ch, RemoteEndpoint* peer)
{
    uint8_t hdr[kOobHdrSize];
    if (ch.recv_all(hdr, kOobHdrSize) < 0) return false;
    uint16_t lid = 0; uint32_t nqp = 0;
    std::memcpy(&lid, hdr + 0, 2);
    uint8_t gi = hdr[2];
    std::memcpy(&nqp, hdr + 4, 4);
    union ibv_gid g{};
    std::memcpy(g.raw, hdr + 8, 16);
    uint64_t slab_base = 0, slab_len = 0;
    uint32_t slab_rkey = 0;
    std::memcpy(&slab_base, hdr + 24, 8);
    std::memcpy(&slab_len,  hdr + 32, 8);
    std::memcpy(&slab_rkey, hdr + 40, 4);
    uint64_t gpu_base = 0, gpu_len = 0;
    uint32_t gpu_rkey = 0;
    std::memcpy(&gpu_base, hdr + 48, 8);
    std::memcpy(&gpu_len,  hdr + 56, 8);
    std::memcpy(&gpu_rkey, hdr + 64, 4);
    bool gpu_enabled = hdr[68] != 0;

    std::vector<uint32_t> qpns(nqp);
    if (nqp && ch.recv_all(qpns.data(), (size_t)nqp * 4) < 0) return false;

    peer->lid        = lid;
    peer->gid_index  = gi;
    peer->gid        = g;
    peer->slab_base  = slab_base;
    peer->slab_len   = slab_len;
    peer->slab_rkey  = slab_rkey;
    peer->gpu_enabled = gpu_enabled;
    peer->gpu_base   = gpu_base;
    peer->gpu_len    = gpu_len;
    peer->gpu_rkey   = gpu_rkey;
    peer->qpns       = std::move(qpns);
    return true;
}

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
                   RemoteEndpoint* peer)
{
    TcpFallback ch;
    if (is_listener) {
        NR_INFO("OOB: listening %s:%u", self_ip.c_str(), oob_port);
        if (!ch.listen(self_ip, oob_port)) {
            NR_ERROR("OOB listen failed");
            return false;
        }
    } else {
        bool ok = false;
        for (int i = 0; i < 60 && !ok; ++i) {
            ok = ch.connect(peer_ip, oob_port);
            if (!ok) std::this_thread::sleep_for(std::chrono::milliseconds(500));
        }
        if (!ok) { NR_ERROR("OOB connect failed after retries"); return false; }
        NR_INFO("OOB: connected to %s:%u", peer_ip.c_str(), oob_port);
    }

    // Exchange. Listener sends first, then receives.
    bool ok;
    if (is_listener) {
        ok = send_info(ch, core, local_slab_base, local_slab_len, local_slab_rkey,
                       local_gpu_enabled, local_gpu_base, local_gpu_len, local_gpu_rkey)
             && recv_info(ch, peer);
    } else {
        ok = recv_info(ch, peer)
             && send_info(ch, core, local_slab_base, local_slab_len, local_slab_rkey,
                          local_gpu_enabled, local_gpu_base, local_gpu_len, local_gpu_rkey);
    }
    if (!ok) { NR_ERROR("OOB exchange failed"); return false; }

    if ((int)peer->qpns.size() != core.num_qp()) {
        NR_ERROR("OOB qp count mismatch local=%d remote=%d",
                 core.num_qp(), (int)peer->qpns.size());
        return false;
    }

    NR_INFO("OOB exchanged: peer lid=%u gid_idx=%u num_qp=%u slab=0x%lx+%lu rkey=0x%x gpu=%s gpu=0x%lx+%lu rkey=0x%x",
            peer->lid, peer->gid_index, (unsigned)peer->qpns.size(),
            (unsigned long)peer->slab_base,
            (unsigned long)peer->slab_len, peer->slab_rkey,
            peer->gpu_enabled ? "true" : "false",
            (unsigned long)peer->gpu_base,
            (unsigned long)peer->gpu_len, peer->gpu_rkey);

    for (int i = 0; i < core.num_qp(); ++i) {
        if (!core.connect_qp(i, peer->qpns[i], peer->lid,
                             peer->gid, peer->gid_index)) {
            NR_ERROR("connect_qp[%d] failed", i);
            return false;
        }
    }

    // Final barrier before tearing down OOB.
    char ack = 0x42;
    if (is_listener) {
        if (ch.send_all(&ack, 1) < 0 || ch.recv_all(&ack, 1) < 0)
            NR_WARN("OOB final ack mismatch (listener)");
    } else {
        if (ch.recv_all(&ack, 1) < 0 || ch.send_all(&ack, 1) < 0)
            NR_WARN("OOB final ack mismatch (connector)");
    }
    ch.close();
    return true;
}

} // namespace nr
