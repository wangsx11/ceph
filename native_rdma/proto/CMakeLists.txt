find_package(Protobuf REQUIRED)

set(PROTO_FILES
    control.proto
    metrics.proto
)

protobuf_generate_cpp(PROTO_SRCS PROTO_HDRS ${PROTO_FILES})

add_library(native_rdma_proto STATIC
    ${PROTO_SRCS} ${PROTO_HDRS}
)

target_include_directories(native_rdma_proto PUBLIC
    ${CMAKE_CURRENT_BINARY_DIR}
    ${Protobuf_INCLUDE_DIRS}
)

target_link_libraries(native_rdma_proto PUBLIC
    ${Protobuf_LIBRARIES}
)
