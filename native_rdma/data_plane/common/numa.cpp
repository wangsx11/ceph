#include "numa.h"
#include "logger.h"

#include <sched.h>
#include <pthread.h>
#include <sys/mman.h>
#include <unistd.h>
#include <cstdlib>
#include <cstring>
#include <cerrno>

// We deliberately avoid libnuma dependency; use syscalls + sysfs.
// Good enough for 2-node RoCE setup. Upgrade later if needed.

namespace nr {

int current_numa_node() {
    int cpu = sched_getcpu();
    if (cpu < 0) return -1;
    return numa_of_cpu(cpu);
}

int numa_of_cpu(int cpu_id) {
    // /sys/devices/system/cpu/cpuX/topology/physical_package_id is not NUMA.
    // Prefer /sys/devices/system/node/nodeN/cpuX .
    for (int node = 0; node < 64; ++node) {
        char path[256];
        std::snprintf(path, sizeof(path),
                      "/sys/devices/system/node/node%d/cpu%d", node, cpu_id);
        if (access(path, F_OK) == 0) return node;
    }
    return -1;
}

bool bind_thread_to_cpu(int cpu_id) {
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu_id, &set);
    int rc = pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
    if (rc != 0) {
        NR_WARN("bind cpu %d failed: %s", cpu_id, std::strerror(rc));
        return false;
    }
    return true;
}

bool bind_thread_to_numa(int numa_id) {
    // Best-effort: enumerate cpus under node and bind to all of them.
    cpu_set_t set;
    CPU_ZERO(&set);
    char dirp[128];
    std::snprintf(dirp, sizeof(dirp),
                  "/sys/devices/system/node/node%d/cpulist", numa_id);
    FILE* f = std::fopen(dirp, "r");
    if (!f) return false;
    char buf[1024] = {0};
    if (!std::fgets(buf, sizeof(buf), f)) { std::fclose(f); return false; }
    std::fclose(f);
    // parse ranges like "0-19,40-59"
    char* tok = std::strtok(buf, ",\n");
    while (tok) {
        int a, b;
        if (std::sscanf(tok, "%d-%d", &a, &b) == 2) {
            for (int c = a; c <= b; ++c) CPU_SET(c, &set);
        } else if (std::sscanf(tok, "%d", &a) == 1) {
            CPU_SET(a, &set);
        }
        tok = std::strtok(nullptr, ",\n");
    }
    int rc = pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
    return rc == 0;
}

void* alloc_huge(size_t bytes, int /*numa_id*/, size_t /*huge_page_size_bytes*/) {
    // MAP_HUGETLB default is 2MB on x86_64. Caller is responsible for
    // rounding up `bytes` to a multiple of 2MB.
    void* p = mmap(nullptr, bytes,
                   PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS | MAP_HUGETLB,
                   -1, 0);
    if (p == MAP_FAILED) {
        NR_WARN("mmap hugetlb failed (errno=%d %s), fallback to normal pages",
                errno, std::strerror(errno));
        p = mmap(nullptr, bytes, PROT_READ | PROT_WRITE,
                 MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (p == MAP_FAILED) return nullptr;
    }
    return p;
}

void free_huge(void* p, size_t bytes) {
    if (p) munmap(p, bytes);
}

} // namespace nr
