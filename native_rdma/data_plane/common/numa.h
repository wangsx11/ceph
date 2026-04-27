#pragma once
#include <cstdint>
#include <cstddef>

namespace nr {

// NUMA / CPU helpers. Real implementations in numa.cpp.
int  current_numa_node();
bool bind_thread_to_cpu(int cpu_id);
bool bind_thread_to_numa(int numa_id);
int  numa_of_cpu(int cpu_id);

// HugePage aware aligned allocation (returns nullptr on failure).
// `huge_page_size_bytes` = 0 means let mmap pick (MAP_HUGETLB default 2MB).
void* alloc_huge(size_t bytes, int numa_id = -1,
                 size_t huge_page_size_bytes = 2 * 1024 * 1024);
void  free_huge(void* p, size_t bytes);

} // namespace nr
