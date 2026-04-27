#include "cm_handler.h"
#include "../common/logger.h"

// NOTE: This is an intentional skeleton. Full librdmacm bring-up logic will
// land in W1. For now we only stub the API so that the data plane compiles
// and the main loop can proceed to its TCP fallback path.

namespace nr {

bool CmHandler::listen(const std::string& ip, uint16_t port) {
    NR_INFO("CmHandler::listen on %s:%u (stub)", ip.c_str(), port);
    return true;
}

bool CmHandler::connect(const std::string& peer_ip, uint16_t port,
                        const PeerEndpoint& /*local*/,
                        PeerEndpoint* /*remote_out*/)
{
    NR_INFO("CmHandler::connect to %s:%u (stub)", peer_ip.c_str(), port);
    return true;
}

} // namespace nr
