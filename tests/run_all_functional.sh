#!/usr/bin/env bash
# 顶层聚合：顺序执行三个子模块的测试
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
bash "$HERE/functional/storage_heterogeneous/run.sh"
bash "$HERE/functional/rdma_distributed/run.sh"
bash "$HERE/functional/memory_pool/run.sh"
echo "[ALL FUNCTIONAL TESTS PASSED]"
