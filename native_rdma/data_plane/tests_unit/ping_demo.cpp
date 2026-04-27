// RDMA ping demo: verifies that libibverbs + MR registration works.
// Does NOT perform cross-node handshake (that is the job of cm_handler.cpp);
// it only proves that the local device can be opened and MR created.
//
// Run:
//   ./bin/nr_ping_demo --dev mlx5_0 --gid-idx 3

#include "rdma/rdma_core.h"
#include "common/logger.h"

#include <cstring>
#include <cstdlib>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    std::string dev = "mlx5_0";
    uint8_t gid_idx = 3;
    for (int i = 1; i < argc; ++i) {
        std::string s = argv[i];
        auto eq = s.find('=');
        std::string k = s.substr(0, eq);
        std::string v = eq == std::string::npos ? "" : s.substr(eq + 1);
        if (k == "--dev") dev = v;
        if (k == "--gid-idx") gid_idx = (uint8_t)std::stoi(v);
    }

    nr::RdmaCore core;
    nr::RdmaConfig cfg;
    cfg.dev_name  = dev;
    cfg.gid_index = gid_idx;
    cfg.num_qp    = 1;
    cfg.sq_depth  = 64;
    cfg.cq_depth  = 128;
    if (!core.init(cfg)) {
        NR_ERROR("init failed"); return 1;
    }

    const size_t sz = 4096;
    void* buf = nullptr;
    if (posix_memalign(&buf, 4096, sz) != 0) return 2;
    std::memset(buf, 0xAB, sz);
    auto mr = core.reg_mr(buf, sz);
    if (!mr.mr) { NR_ERROR("reg_mr failed"); return 3; }

    NR_INFO("ping demo: MR ok addr=%p len=%zu lkey=0x%x rkey=0x%x",
            buf, sz, mr.lkey, mr.rkey);
    core.dereg_mr(mr);
    free(buf);
    return 0;
}
