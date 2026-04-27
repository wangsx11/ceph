cmake_minimum_required(VERSION 3.16)
project(native_rdma
    VERSION 0.1.0
    DESCRIPTION "Self-built RDMA distributed shared-data system"
    LANGUAGES CXX)

# ---------- Global ----------
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# ---------- Warnings & optimization ----------
add_compile_options(
    -Wall -Wextra -Wno-unused-parameter
    -fno-omit-frame-pointer
)
if(CMAKE_BUILD_TYPE STREQUAL "Release")
    add_compile_options(-O3 -march=native)
endif()

# ---------- Options ----------
option(NR_BUILD_TESTS     "Build unit tests"         ON)
option(NR_USE_IO_URING    "Enable io_uring backend"  ON)
option(NR_USE_ZSTD        "Enable zstd compression"  ON)
option(NR_USE_LZ4         "Enable lz4 compression"   ON)

# ---------- Dependencies ----------
find_package(Threads REQUIRED)
find_package(PkgConfig REQUIRED)

# RDMA
pkg_check_modules(IBVERBS REQUIRED libibverbs)
pkg_check_modules(RDMACM  REQUIRED librdmacm)

# protobuf
find_package(Protobuf REQUIRED)

# io_uring
if(NR_USE_IO_URING)
    pkg_check_modules(LIBURING REQUIRED liburing)
endif()

# zstd / lz4 / xxhash / openssl
if(NR_USE_ZSTD)
    pkg_check_modules(ZSTD REQUIRED libzstd)
endif()
if(NR_USE_LZ4)
    pkg_check_modules(LZ4 REQUIRED liblz4)
endif()
pkg_check_modules(XXHASH libxxhash)
find_package(OpenSSL REQUIRED)

# ---------- Subprojects ----------
add_subdirectory(proto)
add_subdirectory(data_plane)

# ---------- Summary ----------
message(STATUS "==== native_rdma build config ====")
message(STATUS "  Build type   : ${CMAKE_BUILD_TYPE}")
message(STATUS "  C++ std      : ${CMAKE_CXX_STANDARD}")
message(STATUS "  io_uring     : ${NR_USE_IO_URING}")
message(STATUS "  zstd         : ${NR_USE_ZSTD}")
message(STATUS "  lz4          : ${NR_USE_LZ4}")
message(STATUS "  tests        : ${NR_BUILD_TESTS}")
message(STATUS "==================================")
