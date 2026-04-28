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

# 默认演示用 1MB slot / 4GB slab（满足 perf_06 + m6 分级存储需要）
export SLAB_SLOT_SIZE="${SLAB_SLOT_SIZE:-1048576}"
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
[ -x "$ROOT/build/bin/native_rdma_dp" ] || die "build/bin/native_rdma_dp 不存在，请先 cmake --build build -j"
[ -x "$ROOT/build/bin/nr_bench" ]       || warn "build/bin/nr_bench 不存在，m5 压测会失败"

# 4) 清理残留进程（精确匹配路径，避免误杀 ssh 会话）
say "清理残留进程 / IPC"
pkill -9 -f "$ROOT/build/bin/native_rdma_dp" 2>/dev/null || true
pkill -f  "python3 $ROOT/control_plane/app.py" 2>/dev/null || true
# 端口上的 Flask 也可能是别的拷贝，显式终结
PORT_PID=$(ss -tlnp 2>/dev/null | awk -v p=":$FLASK_PORT" '$4 ~ p {print $0}' \
           | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
[ -n "${PORT_PID:-}" ] && kill -9 "$PORT_PID" 2>/dev/null || true
rm -f /tmp/native_rdma-dp.sock /tmp/native_rdma-metrics.shm
sleep 1

# 5) 启动 Data Plane（后台 + 日志 tee 到 logs/dp_$ROLE.log）
say "启动 native_rdma_dp (role=$ROLE)"
nohup bash "$ROOT/scripts/start_node.sh" --role="$ROLE" \
    > "logs/dp_${ROLE}.stdout.log" 2>&1 &
DP_PID=$!
say "  DP pid=$DP_PID"

# 等 UDS 就绪（若对端 DP 未启动，OOB 握手会卡住，最多等 15s）
for i in $(seq 1 30); do
    [ -S /tmp/native_rdma-dp.sock ] && break
    sleep 0.5
    if ! kill -0 "$DP_PID" 2>/dev/null; then
        tail -20 "logs/dp_${ROLE}.log" 2>/dev/null
        die "DP 已退出，检查 logs/dp_${ROLE}.log"
    fi
done
if [ ! -S /tmp/native_rdma-dp.sock ]; then
    warn "等待 UDS 15s 超时。请确认对端 DP 已启动 (PEER_IP=$PEER_IP)"
    warn "对端启动命令: ROLE=$([ "$ROLE" = "A" ] && echo B || echo A) bash scripts/demo_up.sh"
    die "OOB 握手可能未完成"
fi
ok "Data Plane 就绪 (uds=/tmp/native_rdma-dp.sock)"

# 6) 启动 Flask 控制面
say "启动 Flask (port=$FLASK_PORT, role=$ROLE)"
NR_ROLE="$ROLE" NR_CTRL_PORT="$FLASK_PORT" \
NR_UDS_PATH=/tmp/native_rdma-dp.sock \
NR_METRICS_SHM=/tmp/native_rdma-metrics.shm \
NR_DASH_DIR="$ROOT/../dashboard" \
    nohup python3 "$ROOT/control_plane/app.py" \
    > "logs/cp_${ROLE}.stdout.log" 2>&1 &
CP_PID=$!
say "  Flask pid=$CP_PID"

# 等 Flask listen
for i in $(seq 1 30); do
    if curl -s --max-time 1 "http://127.0.0.1:$FLASK_PORT/api/cluster/status" >/dev/null 2>&1; then
        break
    fi
    sleep 0.3
done
if ! curl -s --max-time 1 "http://127.0.0.1:$FLASK_PORT/api/cluster/status" >/dev/null 2>&1; then
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
  ➤ Dashboard:    http://${SELF_IP}:${FLASK_PORT}/?b=${PEER_IP}:$([ "$ROLE" = "A" ] && echo 5001 || echo 5000)
                  (URL 里的 ?b=<peer-host:port> 告诉前端 B 节点的 Flask 在哪)

  ➤ 健康检查:
      curl -s http://${SELF_IP}:${FLASK_PORT}/api/m3/cluster   | python3 -m json.tool
      curl -s http://${SELF_IP}:${FLASK_PORT}/api/cluster/status | python3 -m json.tool

  ➤ 停止本端栈:
      bash scripts/demo_down.sh

  ➤ 日志:
      tail -f logs/dp_${ROLE}.log
      tail -f logs/cp_${ROLE}.stdout.log

EOF
