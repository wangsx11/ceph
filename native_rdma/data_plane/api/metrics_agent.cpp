#include "metrics_agent.h"
#include "../common/logger.h"

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <new>

namespace nr {

bool MetricsAgent::attach(const char* shm_path) {
    fd_ = ::open(shm_path, O_RDWR | O_CREAT, 0644);
    if (fd_ < 0) { NR_ERROR("open %s failed", shm_path); return false; }
    if (::ftruncate(fd_, sizeof(MetricsShared)) != 0) {
        NR_ERROR("ftruncate %s failed", shm_path);
        ::close(fd_); fd_ = -1;
        return false;
    }
    void* p = ::mmap(nullptr, sizeof(MetricsShared),
                     PROT_READ | PROT_WRITE, MAP_SHARED, fd_, 0);
    if (p == MAP_FAILED) {
        NR_ERROR("mmap %s failed", shm_path);
        ::close(fd_); fd_ = -1;
        return false;
    }
    shm_ = new (p) MetricsShared();
    NR_INFO("MetricsAgent attached at %s (%zu bytes)",
            shm_path, sizeof(MetricsShared));
    return true;
}

} // namespace nr
