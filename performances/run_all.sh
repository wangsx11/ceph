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
#   PF-7: 默认 dataplane 备份写后端，需要数据面；PF7_BACKEND=fio 时可不依赖数据面
#   PF-8: 依赖数据面已运行
#   PF-9: 独立 benchmark，不需要数据面
#
# 用法:
#   cd performances
#   bash run_all.sh
#   PERFORMANCE_PROFILE=presentation bash run_all.sh

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export REPO_ROOT
export NR_ASYNC_REPL=1

NATIVE_ROOT="${REPO_ROOT}/native_rdma"
PROFILE="${PERFORMANCE_PROFILE:-full}"
if [ "${1:-}" = "--presentation" ]; then
    PROFILE="presentation"
    shift
fi

REQUESTED_PFS=("$@")
if [ "${#REQUESTED_PFS[@]}" -eq 0 ] && [ -n "${PERFORMANCE_PF_LIST:-}" ]; then
    IFS=', ' read -r -a REQUESTED_PFS <<< "${PERFORMANCE_PF_LIST}"
fi

SSH_PROBE_HOST="${PERF_SSH_PROBE_HOST:-xfusion4}"
SSH_PROBE_TIMEOUT_S="${PERF_SSH_PROBE_TIMEOUT_S:-5}"
SSH_PROBE_INTERVAL_S="${PERF_SSH_PROBE_INTERVAL_S:-10}"
SSH_PROBE_FAIL_LIMIT="${PERF_SSH_PROBE_FAIL_LIMIT:-2}"
START_TIMEOUT_S="${PERF_START_TIMEOUT_S:-180}"

PASS=0
FAIL=0
RESULTS=()
SAFETY_ABORT=0

should_run_pf() {
    local pf="$1"
    if [ "${#REQUESTED_PFS[@]}" -eq 0 ]; then
        return 0
    fi
    local item
    for item in "${REQUESTED_PFS[@]}"; do
        if [ "${item}" = "${pf}" ]; then
            return 0
        fi
    done
    return 1
}

needs_initial_data_plane() {
    local pf
    for pf in PF-1 PF-2 PF-3 PF-4 PF-5 PF-6 PF-7 PF-8; do
        if [ "${pf}" = "PF-7" ] && [ "${PF7_BACKEND:-dataplane}" = "fio" ]; then
            continue
        fi
        if should_run_pf "${pf}"; then
            return 0
        fi
    done
    return 1
}

pf_timeout_s() {
    local pf="$1"
    local env_name="PERF_TIMEOUT_${pf//-/_}_S"
    local override="${!env_name:-}"
    if [ -n "${override}" ]; then
        echo "${override}"
        return
    fi
    case "${pf}" in
        PF-1) echo 180 ;;
        PF-2) echo 45 ;;
        PF-3) echo 120 ;;
        PF-4) echo 120 ;;
        PF-5) echo 90 ;;
        PF-6) echo 160 ;;
        PF-7) echo 45 ;;
        PF-8) echo 60 ;;
        PF-9) echo 60 ;;
        *) echo 120 ;;
    esac
}

ssh_probe_once() {
    local label="$1"
    local ts
    ts="$(date '+%Y-%m-%dT%H:%M:%S%z')"
    if [ -z "${SSH_PROBE_HOST}" ]; then
        echo "[ssh-probe] ${ts} ${label}: skipped (PERF_SSH_PROBE_HOST empty)"
        return 0
    fi
    local started
    started="$(date +%s)"
    local out
    if out="$(timeout "$(( SSH_PROBE_TIMEOUT_S + 2 ))s" ssh \
        -o BatchMode=yes \
        -o ConnectTimeout="${SSH_PROBE_TIMEOUT_S}" \
        "${SSH_PROBE_HOST}" hostname 2>&1)"; then
        local ended
        ended="$(date +%s)"
        echo "[ssh-probe] ${ts} ${label}: PASS host=${SSH_PROBE_HOST} elapsed=$(( ended - started ))s output=${out}"
        return 0
    fi
    local rc=$?
    local ended
    ended="$(date +%s)"
    echo "[ssh-probe] ${ts} ${label}: FAIL host=${SSH_PROBE_HOST} rc=${rc} elapsed=$(( ended - started ))s output=${out}"
    return 1
}

start_probe_loop() {
    local stop_file="$1"
    local fail_file="$2"
    local total_file="$3"
    local label="$4"
    local failures=0
    local total=0
    echo 0 > "${fail_file}"
    echo 0 > "${total_file}"
    while [ ! -e "${stop_file}" ]; do
        total=$(( total + 1 ))
        if ! ssh_probe_once "${label}-during-${total}"; then
            failures=$(( failures + 1 ))
        fi
        echo "${failures}" > "${fail_file}"
        echo "${total}" > "${total_file}"
        local slept=0
        while [ "${slept}" -lt "${SSH_PROBE_INTERVAL_S}" ] && [ ! -e "${stop_file}" ]; do
            sleep 1
            slept=$(( slept + 1 ))
        done
    done
}

run_logged_with_probes() {
    local label="$1"
    local timeout_s="$2"
    local log_file="$3"
    shift 3
    local cmd=("$@")
    local rc

    (
        echo "[guard] label=${label}"
        echo "[guard] timeout_s=${timeout_s}"
        echo "[guard] ssh_probe_host=${SSH_PROBE_HOST}"
        echo "[guard] command=${cmd[*]}"
        if ! ssh_probe_once "${label}-pre"; then
            echo "[guard] pre-run SSH probe failed; refusing to start ${label}"
            exit 90
        fi

        local tmp_dir
        tmp_dir="$(mktemp -d)"
        local stop_file="${tmp_dir}/stop"
        local fail_file="${tmp_dir}/failures"
        local total_file="${tmp_dir}/total"
        start_probe_loop "${stop_file}" "${fail_file}" "${total_file}" "${label}" &
        local probe_pid=$!

        local start_ts end_ts elapsed
        start_ts="$(date +%s)"
        timeout --kill-after=10s "${timeout_s}s" "${cmd[@]}"
        rc=$?
        end_ts="$(date +%s)"
        elapsed=$(( end_ts - start_ts ))

        touch "${stop_file}"
        wait "${probe_pid}" 2>/dev/null || true

        local during_failures during_total
        during_failures="$(cat "${fail_file}" 2>/dev/null || echo 0)"
        during_total="$(cat "${total_file}" 2>/dev/null || echo 0)"
        rm -rf "${tmp_dir}"

        local post_rc=0
        ssh_probe_once "${label}-post" || post_rc=$?
        echo "[guard] elapsed_s=${elapsed}"
        echo "[guard] command_rc=${rc}"
        echo "[guard] ssh_probe_during=${during_total} failures=${during_failures}"
        echo "[guard] ssh_probe_post_rc=${post_rc}"

        if [ "${during_failures}" -ge "${SSH_PROBE_FAIL_LIMIT}" ] || [ "${post_rc}" -ne 0 ]; then
            echo "[guard] SSH probe failure limit reached; stop further high-risk PF execution"
            exit 90
        fi
        exit "${rc}"
    ) 2>&1 | tee "${log_file}"
    rc=${PIPESTATUS[0]}
    return "${rc}"
}

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
    local timeout_s
    timeout_s="$(pf_timeout_s "${pf}")"
    run_logged_with_probes "${pf}" "${timeout_s}" "${pf_dir}/run_all.last.log" \
        bash -c "cd '${pf_dir}' && bash run.sh"
    local rc=$?
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
        if [ "$rc" -eq 90 ]; then
            SAFETY_ABORT=1
        fi
    fi
}

start_dp() {
    echo ""
    echo "================================================================"
    echo "  Start Data Plane"
    echo "================================================================"
    echo "[start] 启动双节点数据面 (NR_ASYNC_REPL=1)..."
    if ! run_logged_with_probes "start-data-plane" "${START_TIMEOUT_S}" \
        "${SCRIPT_DIR}/run_all.start.last.log" \
        bash -c "cd '${NATIVE_ROOT}' && bash start.sh"; then
        echo "[start] 数据面启动失败，停止性能测试。"
        exit 2
    fi
    sleep 5
}

restart_dp() {
    echo ""
    echo "[restart] 恢复默认数据面配置 (NR_ASYNC_REPL=1)..."
    run_logged_with_probes "restart-data-plane" "${START_TIMEOUT_S}" \
        "${SCRIPT_DIR}/run_all.restart.last.log" \
        bash -c "cd '${NATIVE_ROOT}' && bash start.sh" >/dev/null || return 1
    sleep 5
}

echo "================================================================"
echo "  Performance Test Suite - $(date '+%Y-%m-%d %H:%M:%S')"
echo "  NR_ASYNC_REPL=${NR_ASYNC_REPL}"
echo "  PERFORMANCE_PROFILE=${PROFILE}"
if [ "${#REQUESTED_PFS[@]}" -gt 0 ]; then
    echo "  PERFORMANCE_PF_LIST=${REQUESTED_PFS[*]}"
fi
echo "================================================================"

if [ "${PROFILE}" = "presentation" ]; then
    echo "[presentation] preparing presentation performance result"
    ts="$(date '+%Y%m%d_%H%M%S')"
    hist="${SCRIPT_DIR}/history/presentation_cli_${ts}"
    tmp="$(mktemp -d)"
    mkdir -p "${hist}"
    [ -f "${SCRIPT_DIR}/summary.md" ] && cp "${SCRIPT_DIR}/summary.md" "${tmp}/summary.md"
    [ -f "${SCRIPT_DIR}/raw.json" ] && cp "${SCRIPT_DIR}/raw.json" "${tmp}/raw.json"
    python3 "${SCRIPT_DIR}/run_all.py" --presentation
    rc=$?
    [ -f "${SCRIPT_DIR}/summary.md" ] && cp "${SCRIPT_DIR}/summary.md" "${hist}/summary.md"
    [ -f "${SCRIPT_DIR}/raw.json" ] && cp "${SCRIPT_DIR}/raw.json" "${hist}/raw.json"
    if [ -f "${tmp}/summary.md" ]; then cp "${tmp}/summary.md" "${SCRIPT_DIR}/summary.md"; fi
    if [ -f "${tmp}/raw.json" ]; then cp "${tmp}/raw.json" "${SCRIPT_DIR}/raw.json"; fi
    rm -rf "${tmp}"
    echo "[presentation] result copied to ${hist}"
    exit "${rc}"
fi

if needs_initial_data_plane; then
    start_dp
fi

# PF-1: 自动重启（1MB slab 测带宽 → 4KB slab 测吞吐）
# 完成后数据面是 4KB slab + NR_ASYNC_REPL=1
if should_run_pf PF-1; then run_pf PF-1; fi
if [ "${SAFETY_ABORT}" -eq 1 ]; then goto_summary=1; else goto_summary=0; fi

# PF-2: 依赖 PF-1 留下的数据面
if [ "${goto_summary}" -eq 0 ] && should_run_pf PF-2; then run_pf PF-2; fi

# PF-3: 自动重启（使用数据面默认自适应 QoS）
if [ "${SAFETY_ABORT}" -eq 0 ] && should_run_pf PF-3; then run_pf PF-3; fi

# PF-3 会并发施压 QoS，重启一次给 PF-4/5 留出干净数据面
if [ "${SAFETY_ABORT}" -eq 0 ] && should_run_pf PF-3 && { should_run_pf PF-4 || should_run_pf PF-5; }; then
    restart_dp || SAFETY_ABORT=1
fi

# PF-4/5: 依赖默认数据面
if [ "${SAFETY_ABORT}" -eq 0 ] && should_run_pf PF-4; then run_pf PF-4; fi
if [ "${SAFETY_ABORT}" -eq 0 ] && should_run_pf PF-5; then run_pf PF-5; fi

# PF-6: 自动重启（1MB slab），完成后恢复 4KB slab
if [ "${SAFETY_ABORT}" -eq 0 ] && should_run_pf PF-6; then run_pf PF-6; fi

# PF-7: 默认 dataplane 备份写后端；PF7_BACKEND=fio 时可不依赖数据面
if [ "${SAFETY_ABORT}" -eq 0 ] && should_run_pf PF-7; then run_pf PF-7; fi

# PF-8: 依赖数据面（PF-6 结束后已恢复 4KB slab）
if [ "${SAFETY_ABORT}" -eq 0 ] && should_run_pf PF-8; then run_pf PF-8; fi

# PF-9: 独立 benchmark，不需要数据面
if [ "${SAFETY_ABORT}" -eq 0 ] && should_run_pf PF-9; then run_pf PF-9; fi

python3 "${SCRIPT_DIR}/run_all.py" --refresh-summary >/dev/null || true

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

if [ "${SAFETY_ABORT}" -eq 1 ]; then
    echo "Stopped early because SSH probes failed repeatedly."
    exit 90
elif [ "$FAIL" -eq 0 ]; then
    echo "All tests PASSED."
    exit 0
else
    echo "${FAIL} test(s) FAILED."
    exit 1
fi
