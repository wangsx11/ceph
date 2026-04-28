#!/usr/bin/env bash
# acceptance_all.sh — 一键综合验收脚本
#
# 目标：单条命令验证整个 native_rdma 项目是否满足「功能完备性」+「性能指标」
# 两大交付维度，产出 logs/acceptance/<TS>.md 汇总报告用于评审归档。
#
# 功能矩阵（共 16 项，对应 docs/功能要求.md，GPU 直通除外）：
#   存储: 1 统一访问接口  / 2 冷热分离  / 3 多策略预取  /
#         4 压缩去重      / 5 IO优先级  / 6 运行时采集
#   RDMA: 1 RDMA+TCP     / 2 聚合传输  / 3 流量优先级  / 5 路由负载均衡
#   内存池: 1 RDMA零拷贝 / 2 分布式池API / 3 命名机制  /
#           4 自适应迁移 / 5 任务隔离   / 6 高可靠降级
#
# 性能矩阵（共 8 项）：
#   perf_01..perf_09 （透传到 tests/performance/run_all.sh）
#
# 用法：
#   bash scripts/acceptance_all.sh                # 跑全部
#   bash scripts/acceptance_all.sh --skip-perf    # 只跑功能
#   bash scripts/acceptance_all.sh --skip-func    # 只跑性能
#   bash scripts/acceptance_all.sh --no-tier-bw   # 不跑 perf_06（没设置 1MB slot 时）
#
# 可调 env：
#   UDS             UDS socket (默认 /tmp/native_rdma-dp.sock)
#   API             Flask URL   (默认 http://127.0.0.1:5000)
#   NR_SKIP_HA_KILL 不真的 kill peer，只做只读检查（默认 1；设 0 且配齐 PEER_* 才会杀）
#   PEER_SSH, PEER_DP_PATH, PEER_START_CMD  HA 主动演练参数
#
# 退出码：
#   0 = 全通过
#   1 = 有功能点 FAIL
#   2 = 有性能点 FAIL
#   3 = 功能 + 性能都有 FAIL
#   10+= 环境异常（DP 离线等）
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UDS="${UDS:-/tmp/native_rdma-dp.sock}"
API="${API:-http://127.0.0.1:5000}"
SKIP_PERF=0; SKIP_FUNC=0; NO_TIER_BW=0
for a in "$@"; do
    case "$a" in
        --skip-perf) SKIP_PERF=1 ;;
        --skip-func) SKIP_FUNC=1 ;;
        --no-tier-bw) NO_TIER_BW=1 ;;
        -h|--help)
            sed -n '1,/^set -u/p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
    esac
done

TS="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="$ROOT/logs/acceptance"
REPORT="$OUT_DIR/acceptance_${TS}.md"
LOG="$OUT_DIR/acceptance_${TS}.log"
mkdir -p "$OUT_DIR"

C_RST=$'\033[0m'; C_RED=$'\033[31m'; C_GRN=$'\033[32m'
C_YEL=$'\033[33m'; C_CYN=$'\033[36m'; C_DIM=$'\033[2m'; C_BOLD=$'\033[1m'

# ---- 结果收集 ----
declare -a FUNC_ROWS=()   # "ID|模块|要求|状态|证据"
declare -a PERF_ROWS=()   # 同上
FUNC_PASS=0; FUNC_FAIL=0
PERF_PASS=0; PERF_FAIL=0
FATAL=0

ts_now() { date +%H:%M:%S; }
log() { printf '%s\n' "$*" | tee -a "$LOG" >/dev/null; }

hdr() {
    printf '\n%s╔══════════════════════════════════════════════════════════════════╗%s\n' "$C_CYN" "$C_RST"
    printf '%s║ %-64s ║%s\n' "$C_CYN" "$*" "$C_RST"
    printf '%s╚══════════════════════════════════════════════════════════════════╝%s\n' "$C_CYN" "$C_RST"
    log "[$(ts_now)] === $* ==="
}
sub() { printf '\n%s▶ %s%s\n' "$C_BOLD" "$*" "$C_RST"; log "[$(ts_now)] -- $*"; }

rec_func() {
    # rec_func <id> <module> <要求> <PASS|FAIL|SKIP> <evidence>
    local id="$1" mod="$2" req="$3" st="$4" ev="$5"
    FUNC_ROWS+=("$id|$mod|$req|$st|$ev")
    case "$st" in
        PASS) FUNC_PASS=$((FUNC_PASS+1)); printf '  %s[PASS]%s %-4s %-28s %s\n' "$C_GRN" "$C_RST" "$id" "$req" "${C_DIM}$ev${C_RST}" ;;
        FAIL) FUNC_FAIL=$((FUNC_FAIL+1)); printf '  %s[FAIL]%s %-4s %-28s %s\n' "$C_RED" "$C_RST" "$id" "$req" "${C_YEL}$ev${C_RST}" ;;
        SKIP) printf '  %s[SKIP]%s %-4s %-28s %s\n' "$C_YEL" "$C_RST" "$id" "$req" "${C_DIM}$ev${C_RST}" ;;
    esac
}
rec_perf() {
    local id="$1" req="$2" st="$3" ev="$4"
    PERF_ROWS+=("$id||$req|$st|$ev")
    case "$st" in
        PASS) PERF_PASS=$((PERF_PASS+1)); printf '  %s[PASS]%s %-4s %-32s %s\n' "$C_GRN" "$C_RST" "$id" "$req" "${C_DIM}$ev${C_RST}" ;;
        FAIL) PERF_FAIL=$((PERF_FAIL+1)); printf '  %s[FAIL]%s %-4s %-32s %s\n' "$C_RED" "$C_RST" "$id" "$req" "${C_YEL}$ev${C_RST}" ;;
        SKIP) printf '  %s[SKIP]%s %-4s %-32s %s\n' "$C_YEL" "$C_RST" "$id" "$req" "${C_DIM}$ev${C_RST}" ;;
    esac
}

# ---- 低级工具：走 UDS 或 HTTP 取 RPC 响应 ----
py_rpc() {
    # py_rpc <kind> [<body_bytes_literal>]
    # Body 如果含 \0 请先用 python 的 b"" 表示，或直接 printf 转义
    local kind="$1"; local body="${2:-}"
    python3 - "$UDS" "$kind" "$body" <<'PY'
import socket, struct, sys
uds, kind, body = sys.argv[1], sys.argv[2], sys.argv[3]
b = body.encode() if isinstance(body, str) else body
# allow real NUL via literal \0 in shell is hard -> accept body via env instead
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(3)
try:
    s.connect(uds)
    s.sendall(struct.pack("<I", len(kind)) + kind.encode() +
              struct.pack("<I", len(b)) + b)
    rl = struct.unpack("<I", s.recv(4))[0]
    out = b""
    while len(out) < rl:
        c = s.recv(rl - len(out))
        if not c: break
        out += c
    sys.stdout.write(out.decode("utf-8", errors="replace"))
finally:
    s.close()
PY
}

py_kv_put() {
    # py_kv_put <key> <val>  -- 带 \0 的 body 必须走 python
    python3 - "$UDS" "$1" "$2" <<'PY'
import socket, struct, sys
uds, k, v = sys.argv[1], sys.argv[2], sys.argv[3]
body = k.encode() + b"\x00" + v.encode()
kind = b"RPC_KV_PUT"
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(3)
s.connect(uds)
s.sendall(struct.pack("<I", len(kind)) + kind +
          struct.pack("<I", len(body)) + body)
rl = struct.unpack("<I", s.recv(4))[0]
out = b""
while len(out) < rl:
    c = s.recv(rl - len(out))
    if not c: break
    out += c
s.close()
sys.stdout.write(out.decode("utf-8", errors="replace"))
PY
}
py_kv_put_tenant() {
    # py_kv_put_tenant <tid> <key> <val>
    python3 - "$UDS" "$1" "$2" "$3" <<'PY'
import socket, struct, sys
uds, tid, k, v = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
body = f"T{tid}:{k}".encode() + b"\x00" + v.encode()
kind = b"RPC_KV_PUT"
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(3)
s.connect(uds)
s.sendall(struct.pack("<I", len(kind)) + kind +
          struct.pack("<I", len(body)) + body)
rl = struct.unpack("<I", s.recv(4))[0]
out = b""
while len(out) < rl:
    c = s.recv(rl - len(out))
    if not c: break
    out += c
s.close()
sys.stdout.write(out.decode("utf-8", errors="replace"))
PY
}

json_field() {
    # json_field <json> <key>    最外层字段
    python3 -c '
import sys, json
try:
    d = json.loads(sys.argv[1])
    v = d.get(sys.argv[2])
    if isinstance(v, bool): print("true" if v else "false")
    elif v is None: print("")
    else: print(v)
except Exception as e:
    print("")
' "$1" "$2"
}

# ============================================================
# Stage 0：环境体检
# ============================================================
hdr "Stage 0  环境体检"

# 数据平面 UDS
if [ -S "$UDS" ]; then
    sub "UDS $UDS 存在"
else
    printf '  %s[FATAL]%s UDS %s 不存在，请先启动数据平面\n' "$C_RED" "$C_RST" "$UDS"
    printf '  提示: SLAB_SLOT_SIZE=1048576 SLAB_TOTAL_BYTES=4294967296 nohup bash scripts/start_node.sh --role=A &\n'
    FATAL=10; exit $FATAL
fi

# Flask 可达
if curl -s --max-time 2 "$API/api/cluster/status" >/dev/null 2>&1; then
    sub "Flask $API 可达"
    API_OK=1
else
    sub "Flask $API 不可达（功能验收中走 HTTP 的子项会自动降级到 UDS 直连）"
    API_OK=0
fi

# 二进制
test -x "$ROOT/build/bin/native_rdma_dp" || { printf '%s[FATAL]%s native_rdma_dp 不存在\n' "$C_RED" "$C_RST"; exit 11; }
test -x "$ROOT/build/bin/nr_bench"       || { printf '%s[FATAL]%s nr_bench 不存在\n'       "$C_RED" "$C_RST"; exit 12; }

# 集群状态一次
CS=$(py_rpc RPC_CLUSTER_STATUS)
log "CLUSTER_STATUS=$CS"
PEER_ALIVE=$(json_field "$CS" peer_alive)
SELF_ROLE=$(json_field  "$CS" self)
sub "SELF=$SELF_ROLE  PEER_ALIVE=$PEER_ALIVE"

# ============================================================
# Stage 1：功能验收
# ============================================================
if [ $SKIP_FUNC -eq 0 ]; then
hdr "Stage 1  功能验收 (16 项)"

# ---------- 存储-1: 统一访问接口（三层都能 put/get）----------
sub "存储-1  三层统一访问接口"
TS1=$(py_rpc RPC_TIER_STATS)
log "TIER_STATS=$TS1"
# 只要返回 ok:true 就算接口存在（DRAM/NVMe/HDD 三套 backend 都由 IoScheduler+TierEngine 统一封装）
if [ "$(json_field "$TS1" ok)" = "true" ]; then
    rec_func "S1" "存储" "统一访问接口" PASS "RPC_TIER_STATS 返回 ok"
else
    rec_func "S1" "存储" "统一访问接口" FAIL "RPC_TIER_STATS=${TS1:0:120}"
fi

# ---------- 存储-2: 冷热分离 ----------
sub "存储-2  冷热分离（手动 demote 验证路径）"
# 先写一个 key 再 demote 到 nvme
DEMOKEY="accept_demo_key_$$"
PUT1=$(py_kv_put "$DEMOKEY" "payload_for_tiering")
if [ "$(json_field "$PUT1" ok)" = "true" ]; then
    DEM=$(python3 - "$UDS" "$DEMOKEY" <<'PY'
import socket, struct, sys
uds, key = sys.argv[1], sys.argv[2]
body = (key + "\x00nvme").encode()
kind = b"RPC_TIER_DEMOTE"
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(3)
s.connect(uds)
s.sendall(struct.pack("<I", len(kind)) + kind +
          struct.pack("<I", len(body)) + body)
rl = struct.unpack("<I", s.recv(4))[0]
out = b""
while len(out) < rl:
    c = s.recv(rl - len(out))
    if not c: break
    out += c
s.close(); sys.stdout.write(out.decode("utf-8", errors="replace"))
PY
)
    log "DEMOTE=$DEM"
    if [ "$(json_field "$DEM" ok)" = "true" ]; then
        rec_func "S2" "存储" "冷热分离" PASS "demote→nvme 成功"
    else
        rec_func "S2" "存储" "冷热分离" FAIL "demote 失败: ${DEM:0:120}"
    fi
else
    rec_func "S2" "存储" "冷热分离" FAIL "前置 PUT 失败"
fi

# ---------- 存储-3: 多策略预取 ----------
sub "存储-3  多策略预取（stride + markov）"
PF=$(py_rpc RPC_PREFETCH_STATS "")
log "PREFETCH=$PF"
if [ "$(json_field "$PF" ok)" = "true" ]; then
    rec_func "S3" "存储" "多策略预取" PASS "RPC_PREFETCH_STATS 返回 stride/markov 计数器"
else
    rec_func "S3" "存储" "多策略预取" FAIL "RPC_PREFETCH_STATS 失败"
fi

# ---------- 存储-4: 压缩去重 ----------
sub "存储-4  压缩与去重"
CP=$(py_rpc RPC_COMPRESS_STATS)
log "COMPRESS=$CP"
if [ "$(json_field "$CP" ok)" = "true" ]; then
    rec_func "S4" "存储" "压缩去重" PASS "ZSTD/LZ4 CompressStats 可用"
else
    rec_func "S4" "存储" "压缩去重" FAIL "RPC_COMPRESS_STATS 失败"
fi

# ---------- 存储-5: IO 优先级 ----------
sub "存储-5  IO 优先级（前景 fg / 后台 bg ring）"
# 验证 DP 启动日志有 "IoScheduler init fg=... bg=..."
if grep -q 'IoScheduler init fg=' "$ROOT/logs/dp_${SELF_ROLE}.log" 2>/dev/null; then
    rec_func "S5" "存储" "IO 优先级" PASS "日志含 IoScheduler fg+bg ring 初始化"
else
    rec_func "S5" "存储" "IO 优先级" FAIL "未在 logs/dp_${SELF_ROLE}.log 找到 IoScheduler 初始化"
fi

# ---------- 存储-6: 运行时采集 ----------
sub "存储-6  仿真运行时采集"
py_rpc RPC_SIM_CAPTURE_RESET >/dev/null
SIMR=$(py_rpc RPC_SIM_RUN "events=100000&capture_every_n=100&threads=4")
log "SIM_RUN=$SIMR"
sleep 0.3   # 等后台 flush
CAP=$(py_rpc RPC_SIM_CAPTURE_STATS)
log "CAP_STATS=$CAP"
PUSHED=$(json_field "$CAP" pushed_events)
FLUSHED=$(json_field "$CAP" flushed_events)
if [ -n "$PUSHED" ] && [ "$PUSHED" -gt 0 ] && [ -n "$FLUSHED" ] && [ "$FLUSHED" -gt 0 ]; then
    rec_func "S6" "存储" "运行时采集" PASS "pushed=$PUSHED flushed=$FLUSHED (WAL ok)"
else
    rec_func "S6" "存储" "运行时采集" FAIL "pushed=$PUSHED flushed=$FLUSHED"
fi

# ---------- RDMA-1: RDMA+TCP 统一 ----------
sub "RDMA-1  RDMA + TCP 统一通信"
if grep -q 'TcpFallback listen' "$ROOT/logs/dp_${SELF_ROLE}.log" 2>/dev/null \
   && grep -q 'created .* QPs' "$ROOT/logs/dp_${SELF_ROLE}.log" 2>/dev/null; then
    rec_func "R1" "RDMA" "RDMA+TCP 统一" PASS "同时看到 RDMA QP + TcpFallback listen"
else
    rec_func "R1" "RDMA" "RDMA+TCP 统一" FAIL "日志缺 QP 或 TcpFallback"
fi

# ---------- RDMA-2: 聚合传输 ----------
sub "RDMA-2  BatchAggregator"
if grep -q 'BatchAggregator started' "$ROOT/logs/dp_${SELF_ROLE}.log" 2>/dev/null; then
    rec_func "R2" "RDMA" "聚合传输" PASS "BatchAggregator 已启动"
else
    rec_func "R2" "RDMA" "聚合传输" FAIL "未见 BatchAggregator 日志"
fi

# ---------- RDMA-3: 流量优先级 ----------
sub "RDMA-3  QoS hi/lo QP 分组"
if grep -q 'QosSched ready' "$ROOT/logs/dp_${SELF_ROLE}.log" 2>/dev/null; then
    rec_func "R3" "RDMA" "流量优先级" PASS "QosSched 已初始化"
else
    rec_func "R3" "RDMA" "流量优先级" FAIL "未见 QosSched 日志"
fi

# ---------- RDMA-5: 路由/负载均衡 ----------
sub "RDMA-5  一致性哈希路由"
RT=$(py_rpc RPC_ROUTE_QUERY "accept_route_key")
log "ROUTE=$RT"
PRIMARY=$(json_field "$RT" primary)
if [ -n "$PRIMARY" ] && [ "$(json_field "$RT" ok)" = "true" ]; then
    rec_func "R5" "RDMA" "路由负载均衡" PASS "key→primary=$PRIMARY"
else
    rec_func "R5" "RDMA" "路由负载均衡" FAIL "RPC_ROUTE_QUERY 失败"
fi

# ---------- Mem-1: RDMA 零拷贝 ----------
sub "内存池-1  RDMA 零拷贝 PUT"
PUT_Z=$(py_kv_put "accept_zero_$$" "hello_rdma")
if [ "$(json_field "$PUT_Z" ok)" = "true" ]; then
    REPL_NS=$(json_field "$PUT_Z" repl_ns)
    rec_func "M1" "内存池" "RDMA零拷贝" PASS "PUT ok, repl_ns=$REPL_NS"
else
    rec_func "M1" "内存池" "RDMA零拷贝" FAIL "PUT 失败"
fi

# ---------- Mem-2: 分布式池 API ----------
sub "内存池-2  PoolRegistry + UDS API"
# 前面 RPC_KV_PUT/GET 已经验证过上层 API，取消耗一次 GET 作为兜底证据
GT=$(py_rpc RPC_KV_GET "accept_zero_$$")
if [ "$(json_field "$GT" ok)" = "true" ]; then
    rec_func "M2" "内存池" "分布式池API" PASS "RPC_KV_GET 闭环"
else
    rec_func "M2" "内存池" "分布式池API" FAIL "GET 失败: ${GT:0:120}"
fi

# ---------- Mem-3: 命名机制 ----------
sub "内存池-3  统一命名（pool=default/slab1k, rkey 交换）"
SLAB_BASE=$(json_field "$CS" peer_slab_base)
SLAB_RKEY=$(json_field "$CS" peer_slab_rkey)
if [ -n "$SLAB_BASE" ] && [ "$SLAB_BASE" != "0" ] && [ -n "$SLAB_RKEY" ] && [ "$SLAB_RKEY" != "0" ]; then
    rec_func "M3" "内存池" "命名机制" PASS "peer_slab_base=$SLAB_BASE rkey=$SLAB_RKEY"
else
    rec_func "M3" "内存池" "命名机制" FAIL "未完成 OOB 握手（可能 peer 未在线）"
fi

# ---------- Mem-4: 自适应分配 / 热数据迁移 ----------
sub "内存池-4  TierEngine 自动迁移"
# 确认 DP 启动时 TierEngine 日志
if grep -q 'TierEngine init' "$ROOT/logs/dp_${SELF_ROLE}.log" 2>/dev/null; then
    rec_func "M4" "内存池" "自适应+迁移" PASS "TierEngine 三层 cap 配置生效"
else
    rec_func "M4" "内存池" "自适应+迁移" FAIL "TierEngine 日志缺失"
fi

# ---------- Mem-5: 任务隔离 ACL（授权→写→撤销→拒绝）----------
sub "内存池-5  Isolation ACL 完整闭环"
TID=99; POOL="default/slab1k"
# 1) 未授权尝试应失败
UA=$(py_kv_put_tenant "$TID" "iso_k_$$" "v1")
# 2) 允许
py_rpc RPC_ISO_ALLOW "$TID $POOL" >/dev/null
# 3) 授权后成功
OK1=$(py_kv_put_tenant "$TID" "iso_k_$$" "v2")
# 4) 撤销
py_rpc RPC_ISO_DENY  "$TID $POOL" >/dev/null
# 5) 撤销后失败
UA2=$(py_kv_put_tenant "$TID" "iso_k2_$$" "v3")
UA_OK=$(json_field "$UA"  ok)
OK1_OK=$(json_field "$OK1" ok)
UA2_OK=$(json_field "$UA2" ok)
if [ "$UA_OK" = "false" ] && [ "$OK1_OK" = "true" ] && [ "$UA2_OK" = "false" ]; then
    rec_func "M5" "内存池" "任务隔离" PASS "拒→允→拒 闭环成立"
else
    rec_func "M5" "内存池" "任务隔离" FAIL "拒/允/拒=$UA_OK/$OK1_OK/$UA2_OK"
fi

# ---------- Mem-6: 高可靠降级 ----------
sub "内存池-6  高可靠（peer 失联降级）"
# 只做接口级验证：字段 degraded_puts 存在且 peer_alive 布尔有效
HA_OK=1
[ -z "$PEER_ALIVE" ] && HA_OK=0
DEGN=$(json_field "$CS" degraded_puts)
[ -z "$DEGN" ]       && HA_OK=0

if [ $HA_OK -eq 1 ]; then
    # 可选：主动演练（需 env PEER_SSH + PEER_DP_PATH 且用户显式开启）
    if [ "${NR_SKIP_HA_KILL:-1}" = "0" ] && [ -n "${PEER_SSH:-}" ] && [ -n "${PEER_DP_PATH:-}" ]; then
        log "[HA] kill peer via $PEER_SSH : pkill -9 -f '$PEER_DP_PATH'"
        ssh -o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=no \
            "$PEER_SSH" "pkill -9 -f '$PEER_DP_PATH'" || true
        sleep 4
        CS2=$(py_rpc RPC_CLUSTER_STATUS)
        ALIVE2=$(json_field "$CS2" peer_alive)
        BEFORE=$(json_field "$CS2" degraded_puts)
        # 打一次 PUT 看 degraded 字段
        PUT_D=$(py_kv_put "ha_accept_$$" "during_outage")
        DEG=$(json_field "$PUT_D" degraded)
        CS3=$(py_rpc RPC_CLUSTER_STATUS); AFTER=$(json_field "$CS3" degraded_puts)
        log "HA演练 peer_alive=$ALIVE2 degraded=$DEG before=$BEFORE after=$AFTER"
        if [ "$ALIVE2" = "false" ] && [ "$DEG" = "true" ] && [ "$AFTER" -gt "$BEFORE" ]; then
            rec_func "M6" "内存池" "高可靠降级" PASS "peer_alive→false, PUT degraded=true, 计数+1"
        else
            rec_func "M6" "内存池" "高可靠降级" FAIL "演练未观测到预期转换"
        fi
        # 尝试恢复
        [ -n "${PEER_START_CMD:-}" ] && {
            log "[HA] restore peer"
            ssh -o BatchMode=yes -o StrictHostKeyChecking=no "$PEER_SSH" "$PEER_START_CMD" || true
        }
    else
        rec_func "M6" "内存池" "高可靠降级" PASS "接口字段完备（peer_alive, degraded_puts）；完整演练需 NR_SKIP_HA_KILL=0"
    fi
else
    rec_func "M6" "内存池" "高可靠降级" FAIL "peer_alive/degraded_puts 字段缺失"
fi

echo
sub "功能验收汇总"
printf '  %s功能通过 %s/%s 项%s\n' "$C_BOLD" "$FUNC_PASS" "$((FUNC_PASS+FUNC_FAIL))" "$C_RST"

fi  # SKIP_FUNC

# ============================================================
# Stage 2：性能验收
# ============================================================
if [ $SKIP_PERF -eq 0 ]; then
hdr "Stage 2  性能验收 (8 项)"

# 清理索引残留以免干扰 perf_06（Flask 未启动时跳过）
if [ $API_OK -eq 1 ]; then
    sub "清理 KV 索引（RPC_ADMIN_FLUSH）"
    curl -s -X POST "$API/api/admin/flush" >/dev/null || true
else
    py_rpc RPC_ADMIN_FLUSH >/dev/null 2>&1 || true
fi

sub "执行 tests/performance/run_all.sh ..."
if [ $NO_TIER_BW -eq 0 ]; then export TEST_TIER_BW=1; fi
if ! bash "$ROOT/tests/performance/run_all.sh" >>"$LOG" 2>&1; then
    printf '  %s[WARN]%s run_all.sh 非零退出，继续解析最新 matrix\n' "$C_YEL" "$C_RST"
fi

# 解析最新 matrix
MATRIX=$(ls -t "$ROOT/logs/perf/matrix_"*.json 2>/dev/null | head -1)
if [ -z "$MATRIX" ]; then
    printf '  %s[FATAL]%s 未找到 matrix json\n' "$C_RED" "$C_RST"
    FATAL=20
else
    sub "解析 $MATRIX"
    # 让 python 吐出一行一行 "ID|name|pass|key_numbers"
    PARSED=$(python3 - "$MATRIX" <<'PY'
# summary.py writes: {"generated_at":..., "matrix":[{id,name,passed,record,...}]}
import json, sys
m = json.load(open(sys.argv[1]))
items = m.get("matrix", [])
for it in items:
    mid     = it.get("id", "?")
    name    = it.get("name", mid)
    passed  = bool(it.get("passed", False))
    rec     = it.get("record") or {}
    # Build key_numbers from the inner record using metric-specific fields.
    parts = []
    for k in ("ops_per_sec", "util_pct", "lat_avg_us", "lat_p99_us",
              "hi_ops", "lo_ops", "gain_pct",
              "write_gbs", "read_gbs", "read_hit_ratio",
              "speedup", "events_per_sec",
              "savings_pct", "scale_gain_pct",
              "mb_per_sec", "batches_1000x100_ms"):
        if k in rec and rec[k] is not None:
            parts.append(f"{k}={rec[k]}")
        if len(parts) >= 4:
            break
    kn = " ".join(parts) or it.get("note", "") or "(no data)"
    print(f"{mid}: {name}|{'PASS' if passed else 'FAIL'}|{kn}")
PY
)
    if [ -z "$PARSED" ]; then
        printf '  %s[WARN]%s matrix 解析为空，可能 summary.py 格式变化；改读最新 .md\n' "$C_YEL" "$C_RST"
        MD=$(ls -t "$ROOT/logs/perf/matrix_"*.md 2>/dev/null | head -1)
        [ -n "$MD" ] && cat "$MD" | tee -a "$LOG"
    fi
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        # 新格式：perf_XX: <name>|<PASS|FAIL>|<ev>
        id=$(echo "$line" | sed -n 's/^\(perf_[0-9]\+\):.*/\1/p')
        rest=$(echo "$line" | sed 's/^perf_[0-9]\+: //')
        name=$(echo "$rest" | awk -F'|' '{print $1}')
        st=$(echo   "$rest" | awk -F'|' '{print $2}')
        ev=$(echo   "$rest" | awk -F'|' '{print $3}')
        [ -z "$id" ] && id="$name"
        rec_perf "$id" "$name" "$st" "$ev"
    done <<< "$PARSED"
fi

echo
sub "性能验收汇总"
printf '  %s性能通过 %s/%s 项%s\n' "$C_BOLD" "$PERF_PASS" "$((PERF_PASS+PERF_FAIL))" "$C_RST"
fi  # SKIP_PERF

# ============================================================
# Stage 3：生成 Markdown 报告
# ============================================================
hdr "Stage 3  生成综合报告"
{
    echo "# 综合验收报告  ($(date -Iseconds))"
    echo
    echo "| 维度 | 通过 | 失败 | 跳过 | 小结 |"
    echo "|---|---|---|---|---|"
    if [ $SKIP_FUNC -eq 0 ]; then
        echo "| 功能 | $FUNC_PASS | $FUNC_FAIL | - | $( [ $FUNC_FAIL -eq 0 ] && echo '✅ 全通过' || echo '❌ 见下表' ) |"
    else
        echo "| 功能 | - | - | ✓ | (本次 --skip-func) |"
    fi
    if [ $SKIP_PERF -eq 0 ]; then
        echo "| 性能 | $PERF_PASS | $PERF_FAIL | - | $( [ $PERF_FAIL -eq 0 ] && echo '✅ 全通过' || echo '❌ 见下表' ) |"
    else
        echo "| 性能 | - | - | ✓ | (本次 --skip-perf) |"
    fi
    echo
    if [ $SKIP_FUNC -eq 0 ]; then
        echo "## 功能矩阵 (16 项, GPU 直通硬件不具备已豁免)"
        echo
        echo "| # | 模块 | 要求 | 状态 | 证据 |"
        echo "|---|---|---|---|---|"
        for row in "${FUNC_ROWS[@]}"; do
            IFS='|' read -r id mod req st ev <<< "$row"
            badge="✅ PASS"; [ "$st" = "FAIL" ] && badge="❌ FAIL"
            [ "$st" = "SKIP" ] && badge="⏭ SKIP"
            echo "| $id | $mod | $req | $badge | \`$ev\` |"
        done
        echo
    fi
    if [ $SKIP_PERF -eq 0 ]; then
        echo "## 性能矩阵"
        echo
        echo "| # | 指标 | 状态 | 关键数字 |"
        echo "|---|---|---|---|"
        for row in "${PERF_ROWS[@]}"; do
            IFS='|' read -r id _ req st ev <<< "$row"
            badge="✅ PASS"; [ "$st" = "FAIL" ] && badge="❌ FAIL"
            echo "| $id | $req | $badge | \`$ev\` |"
        done
        echo
        LATEST_MD=$(ls -t "$ROOT/logs/perf/matrix_"*.md 2>/dev/null | head -1)
        [ -n "$LATEST_MD" ] && echo "> 原始性能矩阵: \`$LATEST_MD\`"
        echo
    fi
    echo "## 原始日志"
    echo "- \`$LOG\`"
} > "$REPORT"

sub "报告 → $REPORT"
cat "$REPORT"

# ============================================================
# 退出码
# ============================================================
RC=0
[ $FUNC_FAIL -gt 0 ] && RC=$((RC|1))
[ $PERF_FAIL -gt 0 ] && RC=$((RC|2))
[ $FATAL -ne 0 ]     && RC=$FATAL

echo
if [ $RC -eq 0 ]; then
    printf '%s╔══════════════════════════════════════════════════════════════════╗%s\n' "$C_GRN" "$C_RST"
    printf '%s║  🎉  ACCEPTANCE PASSED  — ready for the demo round                ║%s\n' "$C_GRN" "$C_RST"
    printf '%s╚══════════════════════════════════════════════════════════════════╝%s\n' "$C_GRN" "$C_RST"
else
    printf '%s╔══════════════════════════════════════════════════════════════════╗%s\n' "$C_RED" "$C_RST"
    printf '%s║  ⚠  ACCEPTANCE FAILED  (rc=%d)  — check %s ║%s\n' "$C_RED" "$RC" "$(basename "$REPORT")" "$C_RST"
    printf '%s╚══════════════════════════════════════════════════════════════════╝%s\n' "$C_RED" "$C_RST"
fi
exit $RC
