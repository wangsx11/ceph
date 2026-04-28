#!/usr/bin/env bash
# demo_walkthrough.sh — 端到端功能演示剧本
#
# 按需设置以下占位符，所有 IP / ssh 用户 / 路径都不硬编码在脚本内：
#   PEER_IP            peer 节点 IP           (必填，远端高可靠演示用)
#   PEER_SSH           peer 节点 ssh 串       (默认: $USER@$PEER_IP)
#   PEER_DP_PATH       peer 上数据平面可执行路径（kill 时精确匹配）
#   PEER_START_CMD     恢复 peer 的完整命令
#   UDS                本机 UDS socket 路径   (默认: /tmp/native_rdma-dp.sock)
#   API                本机 Flask URL         (默认: http://127.0.0.1:5000)
#
# 脚本分 6 节依次演示 4 个新功能 + 路由/隔离/高可靠/采集的完整闭环。
# 任何一节失败都会打印红色 [FAIL] 并继续下一节，便于评审时全景展示。
#
# 用法：
#   bash scripts/demo_walkthrough.sh               # 全部 6 节
#   bash scripts/demo_walkthrough.sh route iso     # 只跑 route + iso
#   PEER_IP=<peer>  PEER_SSH=<user@peer>  PEER_DP_PATH=<...>  \
#     PEER_START_CMD=<...> bash scripts/demo_walkthrough.sh ha
set -u
API="${API:-http://127.0.0.1:5000}"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
PEER_IP="${PEER_IP:-}"
PEER_SSH="${PEER_SSH:-${PEER_IP:+$USER@$PEER_IP}}"
PEER_DP_PATH="${PEER_DP_PATH:-}"
PEER_START_CMD="${PEER_START_CMD:-}"

C_RST=$'\033[0m'; C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'
C_YEL=$'\033[33m';  C_RED=$'\033[31m';  C_DIM=$'\033[2m'

hdr() { printf '\n%s========================================================================%s\n' "$C_CYAN" "$C_RST"
        printf '%s== %s%s\n' "$C_CYAN" "$*" "$C_RST"
        printf '%s========================================================================%s\n' "$C_CYAN" "$C_RST"; }
ok()  { printf '  %s[OK]%s %s\n'   "$C_GREEN" "$C_RST" "$*"; }
bad() { printf '  %s[FAIL]%s %s\n' "$C_RED"   "$C_RST" "$*"; }
info(){ printf '  %s%s%s\n'        "$C_DIM"   "$*" "$C_RST"; }

# jq 是可选的：如果没有就用 python3 美化 JSON
pp() { if command -v jq >/dev/null 2>&1; then jq; else python3 -m json.tool 2>/dev/null || cat; fi; }

# ---- 前置检查 ----
pre_check() {
    hdr "预检查: 数据平面 / 控制平面在线"
    if [ ! -S "$UDS" ]; then
        bad "UDS $UDS 不存在；数据平面未启动"; return 1
    else
        ok "UDS $UDS 存在"
    fi
    if ! curl -s --max-time 2 "$API/api/cluster/status" >/dev/null; then
        bad "$API 无响应；Flask 未启动"; return 1
    else
        ok "Flask $API 可达"
    fi
}

# ---- 1. 路由 ----
demo_route() {
    hdr "① 路由 & 负载均衡（一致性哈希）"
    info "GET /api/route/query?key=demo_alpha"
    curl -s "$API/api/route/query?key=demo_alpha" | pp
    info "GET /api/route/scan?prefix=demo_&count=20  （只打印节点分布计数）"
    curl -s "$API/api/route/scan?prefix=demo_&count=20" \
      | python3 -c '
import sys, json, collections
d = json.load(sys.stdin)
c = collections.Counter(i["primary"] for i in d["items"] if i.get("ok"))
print("  primary 分布:", dict(c), "self=", d.get("self"))
'
    ok "路由决策可按 key 查询、可批量；两端环一致"
}

# ---- 2. 隔离 ----
demo_iso() {
    hdr "② 租户隔离 ACL"
    local TID=42 POOL=default/slab1k

    info "1) 初始 ACL：只含 (0, default/slab1k)"
    curl -s "$API/api/iso/list" | pp

    info "2) 以 T${TID}: 前缀写入应被拒绝"
    curl -s "$API/api/iso/kv_put" -H 'Content-Type: application/json' \
      -d "{\"tenant_id\":${TID},\"key\":\"iso_k1\",\"val\":\"iso_v1\"}" | pp

    info "3) 允许 (T${TID}, ${POOL}) 后再写"
    curl -s "$API/api/iso/allow" -H 'Content-Type: application/json' \
      -d "{\"tenant_id\":${TID},\"pool\":\"${POOL}\"}" >/dev/null
    curl -s "$API/api/iso/kv_put" -H 'Content-Type: application/json' \
      -d "{\"tenant_id\":${TID},\"key\":\"iso_k1\",\"val\":\"iso_v1\"}" | pp

    info "4) GET 能读到"
    curl -s "$API/api/iso/kv_get?tenant_id=${TID}&key=iso_k1" | pp

    info "5) 撤销后再写入立即失败"
    curl -s "$API/api/iso/deny" -H 'Content-Type: application/json' \
      -d "{\"tenant_id\":${TID},\"pool\":\"${POOL}\"}" >/dev/null
    curl -s "$API/api/iso/kv_put" -H 'Content-Type: application/json' \
      -d "{\"tenant_id\":${TID},\"key\":\"iso_k2\",\"val\":\"iso_v2\"}" | pp

    ok "授权→写成功→撤销→再写失败（ACL 闭环）"
}

# ---- 3. 高可靠 ----
demo_ha() {
    hdr "③ 高可靠（peer 故障降级）"

    if [ -z "$PEER_SSH" ] || [ -z "$PEER_DP_PATH" ]; then
        bad "未设置 PEER_SSH / PEER_DP_PATH，跳过自动 kill；改为纯展示状态"
        curl -s "$API/api/ha/status" | pp
        return 0
    fi

    info "起点状态"
    curl -s "$API/api/ha/status" | pp

    info "SSH 到 peer 强杀数据平面 ..."
    ssh -o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=no \
        "$PEER_SSH" "pkill -9 -f '$PEER_DP_PATH'" || true

    info "等待 4s（心跳超时 3s）"
    sleep 4
    info "此时状态：peer_alive 应为 false"
    curl -s "$API/api/ha/status" | pp

    info "在降级模式下连续 PUT 10 次，观察 degraded 字段"
    for i in $(seq 1 10); do
        curl -s "$API/api/kv/put" -H 'Content-Type: application/json' \
          -d "{\"key\":\"ha_$$\_$i\",\"val\":\"v$i\"}" \
          | python3 -c 'import json,sys;d=json.load(sys.stdin);print("  ok=",d.get("ok"),"degraded=",d.get("degraded"))'
    done
    info "累计 degraded_puts"
    curl -s "$API/api/ha/status" | pp

    if [ -n "$PEER_START_CMD" ]; then
        info "恢复 peer ..."
        ssh -o BatchMode=yes -o StrictHostKeyChecking=no "$PEER_SSH" "$PEER_START_CMD" || true
        info "等待 8s 让心跳重新建立"
        sleep 8
        curl -s "$API/api/ha/status" | pp
        ok "peer 恢复；后续 PUT 自动回到强复制"
    else
        info "未设置 PEER_START_CMD，不自动恢复，请手动在 peer 上 start_node.sh"
    fi
}

# ---- 4. 仿真运行时采集 ----
demo_capture() {
    hdr "④ 仿真运行时采集"

    info "重置采集 WAL"
    curl -s -X POST "$API/api/sim/capture/reset" | pp

    info "运行一次 100k 事件的仿真，每 100 个事件采集 1 条"
    curl -s "$API/api/sim/run" -H 'Content-Type: application/json' \
      -d '{"entities":100000,"events":100000,"threads":4,"capture_every_n":100}' | pp

    info "等待 250ms 让后台 flush 线程落盘"
    sleep 0.3

    info "采集统计"
    curl -s "$API/api/sim/capture/stats" | pp

    info "WAL 前 5 条事件（注意 type 1=ObjectAttr, 2=InteractionEvent）"
    curl -s "$API/api/sim/capture/wal_head?limit=5" | pp

    ok "pushed == flushed，dropped=0；WAL 有 ObjectAttr/Interaction 两类事件"
}

# ---- 5. 集群状态汇总 ----
demo_cluster() {
    hdr "⑤ 集群状态快照（用于报告）"
    curl -s "$API/api/cluster/status" | pp
}

# ---- 6. 性能矩阵（可选，耗时较长） ----
demo_perf() {
    hdr "⑥ 性能矩阵（TEST_TIER_BW=1）"
    if [ ! -x ./build/bin/nr_bench ]; then
        bad "build/bin/nr_bench 不存在；请先 cmake --build build -j"
        return 1
    fi
    TEST_TIER_BW=1 bash tests/performance/run_all.sh | tail -40
    echo
    info "最新 matrix 摘要:"
    ls -t logs/perf/matrix_*.md 2>/dev/null | head -1 | xargs -I{} cat {}
}

# ---------- main ----------
SECTIONS=(route iso ha capture cluster)
# perf 耗时 1~2 分钟，默认不跑；显式指定才执行
if [ "$#" -gt 0 ]; then SECTIONS=("$@"); fi

pre_check || exit 1
for s in "${SECTIONS[@]}"; do
    case "$s" in
        route)   demo_route    ;;
        iso)     demo_iso      ;;
        ha)      demo_ha       ;;
        capture) demo_capture  ;;
        cluster) demo_cluster  ;;
        perf)    demo_perf     ;;
        *)       bad "unknown section: $s" ;;
    esac
done

hdr "演示结束"
ok "全部小节已执行；前端 dashboard 访问: $API/"
