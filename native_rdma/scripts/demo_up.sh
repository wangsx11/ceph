#!/usr/bin/env bash
# demo_up.sh — 一键启动演示全套栈（本端视角）
#
# 本脚本只管 **本机** 的 Data Plane + Flask 控制面。远端 peer 的 DP
# 需要你先在 peer 主机上跑起来。演示 §3/§5/§6 都要求"真实跨节点"，
# 因此 peer 必须先在另一台物理机上启动数据平面。
#
# 典型流程（评审现场双节点）：
#   [B端 xfusion4]  ROLE=B bash scripts/demo_up.sh
#   [A端 xfusion3]  ROLE=A bash scripts/demo_up.sh    # A 端同时开 Flask
#   浏览器打开:     http://<A端 IP>:5000/?b=<B端 IP>:5001
#
# 单机调试（非评审）：
#   ROLE=A FLASK_PORT=5000 bash scripts/demo_up.sh
#
# 可选 env：
#   ROLE            A | B           (默认 A)
#   FLASK_PORT      HTTP 端口       (默认 A=5000, B=5001)
#   （其它配置如 SELF_IP/PEER_IP/HDD_PATH 等全部来自 deploy/node_<role>.env，
#     请直接修改该文件，不要在本脚本里 export）
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ROLE="${ROLE:-A}"
FLASK_PORT_DEFAULT=$([ "$ROLE" = "A" ] && echo 5000 || echo 5001)
FLASK_PORT="${FLASK_PORT:-$FLASK_PORT_DEFAULT}"

# 默认演示用 4KB slot / 4GB slab：M5 的 1万/5万/10万 1KB 对象可真实常驻，
# M6 的 4KB 对象也能正常迁移。perf_06 的 1MB 带宽测试请显式覆盖
# SLAB_SLOT_SIZE=1048576 SLAB_TOTAL_BYTES=4294967296。
export SLAB_SLOT_SIZE="${SLAB_SLOT_SIZE:-4096}"
export SLAB_TOTAL_BYTES="${SLAB_TOTAL_BYTES:-4294967296}"

# ---- 色彩输出 ----
C_GRN=$'\033[32m'; C_CYN=$'\033[36m'; C_YEL=$'\033[33m'; C_RED=$'\033[31m'; C_RST=$'\033[0m'
say() { printf '%s[demo_up]%s %s\n' "$C_CYN" "$C_RST" "$*"; }
ok()  { printf '%s[  OK  ]%s %s\n' "$C_GRN" "$C_RST" "$*"; }
warn(){ printf '%s[ WARN ]%s %s\n' "$C_YEL" "$C_RST" "$*"; }
die() { printf '%s[ FAIL ]%s %s\n' "$C_RED" "$C_RST" "$*"; exit 2; }

ENV_FILE="$ROOT/deploy/node_${ROLE,,}.env"
[ -f "$ENV_FILE" ] || die "配置不存在: $ENV_FILE  (请检查 ROLE=$ROLE 是否正确)"
# 临时加载，仅用于本脚本提示输出，不影响后续 start_node.sh 自己再 source 一次
SELF_IP=$(awk -F= '/^SELF_IP=/{print $2}' "$ENV_FILE")
PEER_IP=$(awk -F= '/^PEER_IP=/{print $2}' "$ENV_FILE")

say "ROLE=$ROLE  SELF=$SELF_IP  PEER=$PEER_IP  FLASK_PORT=$FLASK_PORT"
say "SLAB_SLOT_SIZE=$SLAB_SLOT_SIZE  SLAB_TOTAL_BYTES=$SLAB_TOTAL_BYTES"
say "NR_GDR_ENABLE=${NR_GDR_ENABLE:-0}  NR_CUDA_DEVICE=${NR_CUDA_DEVICE:-0}  NR_GDR_BYTES=${NR_GDR_BYTES:-67108864}"

# 1) 日志目录
mkdir -p logs

# 2) 冷层目录：如果 env 里指向一个"已存在但是文件"的路径，搬走
HDD_PATH=$(awk -F= '/^HDD_PATH=/{print $2}' "$ENV_FILE")
if [ -n "$HDD_PATH" ] && [ -e "$HDD_PATH" ] && [ ! -d "$HDD_PATH" ]; then
    warn "冷层路径 $HDD_PATH 是文件而非目录，移动为备份"
    mv "$HDD_PATH" "${HDD_PATH}.bak.$(date +%s)"
fi
mkdir -p "$HDD_PATH" 2>/dev/null || true

# 3) 检查二进制
BUILD_DIR="${NR_BUILD_DIR:-$ROOT/build-current}"
if [ ! -x "$BUILD_DIR/bin/native_rdma_dp" ] && [ -x "$ROOT/build/bin/native_rdma_dp" ]; then
    BUILD_DIR="$ROOT/build"
    export NR_BUILD_DIR="$BUILD_DIR"
fi
[ -x "$BUILD_DIR/bin/native_rdma_dp" ] || die "$BUILD_DIR/bin/native_rdma_dp 不存在，请先 cmake -S . -B \"$BUILD_DIR\" && cmake --build \"$BUILD_DIR\" -j"
[ -x "$BUILD_DIR/bin/nr_bench" ]       || warn "$BUILD_DIR/bin/nr_bench 不存在，m5 压测会失败"

# 4) 清理残留进程（精确匹配路径，避免误杀 ssh 会话）
say "清理残留进程 / IPC"
pkill -9 -f "$BUILD_DIR/bin/native_rdma_dp" 2>/dev/null || true
pkill -9 -f "$ROOT/build/bin/native_rdma_dp" 2>/dev/null || true
pkill -f  "python3 $ROOT/control_plane/app.py" 2>/dev/null || true
# 同一台机器上可能残留来自旧 checkout 的 native_rdma_dp，占用相同 UDS。
# 只清理监听当前 UDS 的 native_rdma_dp，避免误杀其它无关进程。
UDS_OWNER_PID=$(ss -xlp 2>/dev/null | awk -v s="${UDS_PATH:-/tmp/native_rdma-dp.sock}" '$0 ~ s && $0 ~ /native_rdma_dp/ { if (match($0, /pid=[0-9]+/)) { print substr($0, RSTART+4, RLENGTH-4); exit } }')
[ -n "${UDS_OWNER_PID:-}" ] && kill -9 "$UDS_OWNER_PID" 2>/dev/null || true
# 端口上的 Flask 也可能是别的拷贝，显式终结
PORT_PID=$(ss -tlnp 2>/dev/null | awk -v p=":$FLASK_PORT" '$4 ~ p {print $0}' \
           | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
[ -n "${PORT_PID:-}" ] && kill -9 "$PORT_PID" 2>/dev/null || true
rm -f /tmp/native_rdma-dp.sock /tmp/native_rdma-metrics.shm
sleep 1

# 5) 启动 Data Plane（后台 + 日志 tee 到 logs/dp_$ROLE.log）
# 关键：</dev/null + disown 双保险，防止通过 `ssh host "bash demo_up.sh"` 远程
# 启动时，SSH 会话退出后把 DP 和 Flask 一起 SIGHUP 杀掉。
say "启动 native_rdma_dp (role=$ROLE)"
nohup bash "$ROOT/scripts/start_node.sh" --role="$ROLE" \
    </dev/null > "logs/dp_${ROLE}.stdout.log" 2>&1 &
DP_PID=$!
disown "$DP_PID" 2>/dev/null || true
say "  DP pid=$DP_PID"

# ---- 关键：A 与 B 等不同的信号 ----
# 数据平面的 OOB 握手里 role=B 是 listener（监听 TCP 18515），role=A 是
# connector（主动去 connect peer）。UDS 只会在握手成功后才创建。
# 因此：
#   B 启动后：等 TCP:DATA_PORT 进入 LISTEN 状态即视为 OK（A 还没 connect 前
#             UDS 是不会创建的，不能拿 UDS 当"B 就绪"信号）
#   A 启动后：等 UDS socket 出现即 OK（A 这边握手完成才会开 UDS server）
# 这样解决了"A/B 互等 -> 谁先启谁被脚本判死"的鸡蛋悖论。
DATA_PORT=$(awk -F= '/^DATA_PORT=/{print $2}' "$ENV_FILE")
DATA_PORT="${DATA_PORT:-18515}"

if [ "$ROLE" = "B" ]; then
    say "role=B 是 OOB listener，等 TCP:${DATA_PORT} 进入 LISTEN（最多 20s）"
    got_listen=0
    for i in $(seq 1 40); do
        if ss -tln 2>/dev/null | awk '{print $4}' | grep -qE ":${DATA_PORT}$"; then
            got_listen=1; break
        fi
        sleep 0.5
        if ! kill -0 "$DP_PID" 2>/dev/null; then
            tail -20 "logs/dp_${ROLE}.log" 2>/dev/null
            die "DP 已退出，检查 logs/dp_${ROLE}.log"
        fi
    done
    if [ $got_listen -eq 0 ]; then
        tail -20 "logs/dp_${ROLE}.log" 2>/dev/null
        die "TCP:${DATA_PORT} 等待 20s 未进入 LISTEN"
    fi
    ok "Data Plane (B) 已监听 TCP:${DATA_PORT}，等待 A 端 connect 即可完成握手"
    # B 端即便还没 UDS，也先退出脚本 —— A 端起来后会自动完成握手，B 端 UDS
    # 也会随之创建。Flask 暂时无 UDS 可用，但会在 uds_call 时懒重连。
else
    say "role=A 等 UDS 就绪（最多 15s，要求对端 B 已在 listen）"
    got_uds=0
    for i in $(seq 1 30); do
        [ -S /tmp/native_rdma-dp.sock ] && { got_uds=1; break; }
        sleep 0.5
        if ! kill -0 "$DP_PID" 2>/dev/null; then
            tail -20 "logs/dp_${ROLE}.log" 2>/dev/null
            die "DP 已退出，检查 logs/dp_${ROLE}.log"
        fi
    done
    if [ $got_uds -eq 0 ]; then
        warn "UDS 超时。请确认 B 端 (PEER_IP=$PEER_IP) 已在 TCP:${DATA_PORT} LISTEN"
        warn "B 端启动: 在 B 主机上执行  ROLE=B bash scripts/demo_up.sh"
        die "OOB 握手未完成"
    fi
    ok "Data Plane (A) 握手完成 (uds=/tmp/native_rdma-dp.sock)"
fi

# 6) 启动 Flask 控制面
say "启动 Flask (port=$FLASK_PORT, role=$ROLE)"
# 对端 Flask URL 根据约定：A 端默认 5000，B 端默认 5001；对端端口取"反向"默认值
PEER_FLASK_PORT=$([ "$ROLE" = "A" ] && echo 5001 || echo 5000)
PEER_URL="http://${PEER_IP}:${PEER_FLASK_PORT}"
say "  peer url = $PEER_URL （将作为反向代理目标注入 Flask）"

# $ROOT 已经是 <repo>/native_rdma，所以回溯一层到 <repo>/dashboard 即可。
# （之前错写成 ../../dashboard 会跑到 $HOME/dashboard，导致 Flask 加载错面板。）
NR_DASH_DIR_RESOLVED="${NR_DASH_DIR:-$(cd "$ROOT/.." && pwd)/dashboard}"

NR_ROLE="$ROLE" NR_CTRL_PORT="$FLASK_PORT" \
NR_UDS_PATH=/tmp/native_rdma-dp.sock \
NR_METRICS_SHM=/tmp/native_rdma-metrics.shm \
NR_DASH_DIR="$NR_DASH_DIR_RESOLVED" \
NR_PEER_URL="$PEER_URL" \
    nohup python3 "$ROOT/control_plane/app.py" \
    </dev/null > "logs/cp_${ROLE}.stdout.log" 2>&1 &
CP_PID=$!
disown "$CP_PID" 2>/dev/null || true
say "  Flask pid=$CP_PID  dash_dir=$NR_DASH_DIR_RESOLVED"

# 等 Flask listen（只要求 HTTP 有响应即可；此时 B 端若还没完成握手，
# /api/cluster/status 会返回 ok:false + dp_offline，但 HTTP 本身是通的）
got_flask=0
for i in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 1 \
           "http://127.0.0.1:$FLASK_PORT/api/cluster/status" 2>/dev/null || echo 000)
    if [ "$code" = "200" ]; then
        got_flask=1; break
    fi
    sleep 0.3
done
if [ $got_flask -eq 0 ]; then
    tail -20 "logs/cp_${ROLE}.stdout.log" 2>/dev/null
    die "Flask 启动失败，检查 logs/cp_${ROLE}.stdout.log"
fi
ok "Flask 就绪 (http://127.0.0.1:$FLASK_PORT/)"

# 7) 打印提示
cat <<EOF

${C_GRN}═══════════════════════════════════════════════════════════════${C_RST}
  ${C_GRN}演示栈启动完成 (role=$ROLE, self=$SELF_IP)${C_RST}
${C_GRN}═══════════════════════════════════════════════════════════════${C_RST}

  ➤ 本端 Flask:   http://${SELF_IP}:${FLASK_PORT}/
  ➤ Dashboard:    http://${SELF_IP}:${FLASK_PORT}/
                  （前端只连本端 Flask；对端数据自动走 /api/peer/ 反向代理，无需配置 ?b= 参数）

  ➤ 健康检查:
      curl -s http://${SELF_IP}:${FLASK_PORT}/api/demo3/cluster | python3 -m json.tool
      curl -s http://${SELF_IP}:${FLASK_PORT}/api/peer/demo3/cluster | python3 -m json.tool

  ➤ 停止本端栈:
      bash scripts/demo_down.sh

  ➤ 日志:
      tail -f logs/dp_${ROLE}.log
      tail -f logs/cp_${ROLE}.stdout.log

EOF
