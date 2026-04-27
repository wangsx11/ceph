# ---------- common ----------
add_library(nr_common STATIC
    common/logger.cpp
    common/numa.cpp
    common/time_util.cpp
)
target_include_directories(nr_common PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
)
target_link_libraries(nr_common PUBLIC
    Threads::Threads
)

# ---------- rdma core ----------
add_library(nr_rdma STATIC
    rdma/rdma_core.cpp
    rdma/cm_handler.cpp
    rdma/poller.cpp
    rdma/tcp_fallback.cpp
    rdma/oob.cpp
)
target_link_libraries(nr_rdma PUBLIC
    nr_common
    ${IBVERBS_LIBRARIES}
    ${RDMACM_LIBRARIES}
)
target_include_directories(nr_rdma PUBLIC
    ${IBVERBS_INCLUDE_DIRS}
    ${RDMACM_INCLUDE_DIRS}
)

# ---------- mempool ----------
add_library(nr_mempool STATIC
    mempool/slab.cpp
    mempool/arena.cpp
    mempool/pool_registry.cpp
    mempool/isolation.cpp
)
target_link_libraries(nr_mempool PUBLIC nr_rdma)

# ---------- qos ----------
add_library(nr_qos STATIC
    qos/qos_sched.cpp
)
target_link_libraries(nr_qos PUBLIC nr_rdma)

# ---------- batch ----------
add_library(nr_batch STATIC
    batch/batch_aggregator.cpp
)
target_link_libraries(nr_batch PUBLIC nr_rdma)

# ---------- router ----------
add_library(nr_router STATIC
    router/consistent_hash.cpp
    router/object_router.cpp
)
target_link_libraries(nr_router PUBLIC nr_common)

# ---------- storage ----------
set(STORAGE_SRCS
    storage/tier_engine.cpp
    storage/prefetcher.cpp
    storage/compress.cpp
    storage/dedup.cpp
    storage/io_scheduler.cpp
    storage/snapshot.cpp
)
add_library(nr_storage STATIC ${STORAGE_SRCS})
target_link_libraries(nr_storage PUBLIC
    nr_common
    OpenSSL::Crypto
)
if(NR_USE_IO_URING)
    target_link_libraries(nr_storage PUBLIC ${LIBURING_LIBRARIES})
    target_include_directories(nr_storage PUBLIC ${LIBURING_INCLUDE_DIRS})
    target_compile_definitions(nr_storage PUBLIC NR_USE_IO_URING=1)
endif()
if(NR_USE_ZSTD)
    target_link_libraries(nr_storage PUBLIC ${ZSTD_LIBRARIES})
    target_compile_definitions(nr_storage PUBLIC NR_USE_ZSTD=1)
endif()
if(NR_USE_LZ4)
    target_link_libraries(nr_storage PUBLIC ${LZ4_LIBRARIES})
    target_compile_definitions(nr_storage PUBLIC NR_USE_LZ4=1)
endif()

# ---------- replication ----------
add_library(nr_replication STATIC
    replication/replicator.cpp
    replication/heartbeat.cpp
)
target_link_libraries(nr_replication PUBLIC nr_rdma nr_mempool)

# ---------- sim ----------
add_library(nr_sim STATIC
    sim/sim_capture.cpp
    sim/sim_engine.cpp
)
target_link_libraries(nr_sim PUBLIC nr_mempool nr_storage)

# ---------- api ----------
add_library(nr_api STATIC
    api/uds_server.cpp
    api/metrics_agent.cpp
)
target_link_libraries(nr_api PUBLIC
    nr_common
    native_rdma_proto
)

# ---------- main binary ----------
add_executable(native_rdma_dp main.cpp)
target_link_libraries(native_rdma_dp PRIVATE
    nr_rdma
    nr_mempool
    nr_qos
    nr_batch
    nr_router
    nr_storage
    nr_replication
    nr_sim
    nr_api
)
set_target_properties(native_rdma_dp PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin
)

# ---------- unit tests (header-only demo) ----------
if(NR_BUILD_TESTS)
    add_executable(nr_ping_demo tests_unit/ping_demo.cpp)
    target_link_libraries(nr_ping_demo PRIVATE nr_rdma)
    set_target_properties(nr_ping_demo PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin
    )

    # nr_bench: UDS-direct load generator for PUT/GET/MIX.
    add_executable(nr_bench tests_unit/nr_bench.cpp)
    target_link_libraries(nr_bench PRIVATE Threads::Threads)
    set_target_properties(nr_bench PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin
    )

    # nr_mempool_bench: standalone malloc-vs-slab micro-benchmark for
    # docs/自研实施清单.md §7 row #9. Does NOT link the RDMA stack, so it can
    # run anywhere (even without a working RDMA device).
    add_executable(nr_mempool_bench tests_unit/nr_mempool_bench.cpp)
    target_link_libraries(nr_mempool_bench PRIVATE Threads::Threads)
    set_target_properties(nr_mempool_bench PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin
    )
endif()
