#!/usr/bin/env bash
# 一键执行所有 PF-1 到 PF-9 性能测试。
#
# 执行策略:
#   PF-1: 自动重启数据面（1MB slab → 4KB slab），需要 NR_ASYNC_REPL=1
#   PF-2: 依赖数据面已运行（PF-1 结束后 4KB slab 已就位）
#   PF-3: 自动重启数据面（默认自适应 QoS），需要 NR_ASYNC_REPL=1
#   PF-4: 依赖数据面已运行
#   PF-5: 依赖数据面已运行
#   PF-6: 自动重启数据面（1MB slab），需要 NR_ASYNC_REPL=1
#   PF-7: 纯 fio，不需要数据面
#   PF-8: 依赖数据面已运行
#   PF-9: 独立 benchmark，不需要数据面
#
# 用法:
#   cd performances
#   bash run_all.sh

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export REPO_ROOT
export NR_ASYNC_REPL=1

NATIVE_ROOT="${REPO_ROOT}/native_rdma"
PASS=0
FAIL=0
RESULTS=()

run_pf() {
    local pf="$1"
    local pf_dir="${SCRIPT_DIR}/${pf}"
    echo ""
    echo "================================================================"
    echo "  ${pf}"
    echo "================================================================"

    if [ ! -f "${pf_dir}/run.sh" ]; then
        echo "  [SKIP] ${pf}/run.sh not found"
        RESULTS+=("${pf}: SKIP")
        return
    fi

    local start_ts
    start_ts=$(date +%s)
    (cd "${pf_dir}" && bash run.sh) 2>&1 | tee "${pf_dir}/run_all.last.log"
    local rc=${PIPESTATUS[0]}
    local end_ts
    end_ts=$(date +%s)
    local elapsed=$(( end_ts - start_ts ))

    if [ "$rc" -eq 0 ]; then
        echo "  [PASS] ${pf} (${elapsed}s)"
        PASS=$(( PASS + 1 ))
        RESULTS+=("${pf}: PASS (${elapsed}s)")
    else
        echo "  [FAIL] ${pf} exit=${rc} (${elapsed}s)"
        FAIL=$(( FAIL + 1 ))
        RESULTS+=("${pf}: FAIL exit=${rc} (${elapsed}s)")
    fi
}

start_dp() {
    echo ""
    echo "================================================================"
    echo "  Start Data Plane"
    echo "================================================================"
    echo "[start] 启动双节点数据面 (NR_ASYNC_REPL=1)..."
    if ! (cd "${NATIVE_ROOT}" && bash start.sh); then
        echo "[start] 数据面启动失败，停止性能测试。"
        exit 2
    fi
    sleep 5
}

restart_dp() {
    echo ""
    echo "[restart] 恢复默认数据面配置 (NR_ASYNC_REPL=1)..."
    (cd "${NATIVE_ROOT}" && bash start.sh) 2>&1 | tail -3
    sleep 5
}

echo "================================================================"
echo "  Performance Test Suite - $(date '+%Y-%m-%d %H:%M:%S')"
echo "  NR_ASYNC_REPL=${NR_ASYNC_REPL}"
echo "================================================================"

start_dp

# PF-1: 自动重启（1MB slab 测带宽 → 4KB slab 测吞吐）
# 完成后数据面是 4KB slab + NR_ASYNC_REPL=1
run_pf PF-1

# PF-2: 依赖 PF-1 留下的数据面
run_pf PF-2

# PF-3: 自动重启（使用数据面默认自适应 QoS）
run_pf PF-3

# PF-3 会并发施压 QoS，重启一次给 PF-4/5 留出干净数据面
restart_dp

# PF-4/5: 依赖默认数据面
run_pf PF-4
run_pf PF-5

# PF-6: 自动重启（1MB slab），完成后恢复 4KB slab
run_pf PF-6

# PF-7: 纯 fio，不需要数据面
run_pf PF-7

# PF-8: 依赖数据面（PF-6 结束后已恢复 4KB slab）
run_pf PF-8

# PF-9: 独立 benchmark，不需要数据面
run_pf PF-9

# ---- 汇总 ----
TOTAL=$(( PASS + FAIL ))
echo ""
echo "================================================================"
echo "  Summary: ${PASS}/${TOTAL} PASS"
echo "================================================================"
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo "All tests PASSED."
    exit 0
else
    echo "${FAIL} test(s) FAILED."
    exit 1
fi
