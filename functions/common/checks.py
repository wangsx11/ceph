from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Callable

from .runner import (
    FailCheck,
    FnContext,
    SkipCheck,
    pass_result,
    fail_result,
    skip_result,
    waived_result,
    CheckResult,
)


def _ok(data: dict[str, Any]) -> bool:
    return bool(data.get("ok") is True)


def _require_ok(data: dict[str, Any], label: str) -> None:
    if not _ok(data):
        raise FailCheck(f"{label} 返回失败: {data}")


def _unique(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{os.getpid()}"


def _positive_int(value: Any) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def _require_peer_if_needed(ctx: FnContext, status: dict[str, Any]) -> None:
    if ctx.require_peer and not bool(status.get("peer_alive", False)):
        raise SkipCheck("REQUIRE_PEER=1 且 peer_alive=false，跳过需要双节点的验证", {"cluster": status})


def storage_fn1(ctx: FnContext) -> CheckResult:
    stats = ctx.rpc_json("RPC_TIER_STATS")
    fields = ("dram", "nvme", "hdd")
    if _ok(stats) and all(name in stats for name in fields):
        return pass_result(
            f"RPC_TIER_STATS ok: dram={stats.get('dram')} nvme={stats.get('nvme')} hdd={stats.get('hdd')}",
            details={"tier_stats": stats},
        )
    return fail_result("RPC_TIER_STATS 缺少 ok 或层级字段", details={"tier_stats": stats})


def storage_fn2(ctx: FnContext) -> CheckResult:
    key = _unique("fn_storage_tier")
    value = "tiering_probe_payload"
    put = ctx.kv_put(key, value)
    _require_ok(put, "RPC_KV_PUT")
    demote = ctx.rpc_json("RPC_TIER_DEMOTE", key.encode() + b"\x00nvme")
    _require_ok(demote, "RPC_TIER_DEMOTE")
    got = ctx.kv_get(key)
    _require_ok(got, "RPC_KV_GET after demote")
    hit = str(got.get("hit", ""))
    if "nvme" not in hit:
        return fail_result(
            f"demote 成功但 GET 未显示 nvme 命中: hit={hit}",
            details={"put": put, "demote": demote, "get": got},
        )
    return pass_result(
        f"对象 {key} 写入后 demote->nvme 成功，GET hit={hit}",
        details={"put": put, "demote": demote, "get": got},
    )


def storage_fn3(ctx: FnContext) -> CheckResult:
    prefix = _unique("fn_prefetch_")
    items = [(f"{prefix}{i}", f"value-{i}") for i in range(8)]
    for key, val in items:
        _require_ok(ctx.kv_put(key, val), f"PUT {key}")
    for key, _ in items[:4]:
        _require_ok(ctx.kv_get(key), f"GET {key}")
    stats = ctx.rpc_json("RPC_PREFETCH_STATS", items[3][0])
    predicted = stats.get("predicted") or []
    expected = items[4][0]
    if _ok(stats) and int(stats.get("total", 0) or 0) >= 4 and expected in predicted:
        return pass_result(
            f"顺序访问触发 stride 预测: expected={expected} predicted_count={len(predicted)}",
            details={"prefetch_stats": stats},
        )
    return fail_result(
        "RPC_PREFETCH_STATS 未返回预期 stride 预测",
        details={"prefetch_stats": stats, "expected": expected},
    )


def storage_fn4(ctx: FnContext) -> CheckResult:
    before = ctx.rpc_json("RPC_COMPRESS_STATS")
    _require_ok(before, "RPC_COMPRESS_STATS before")
    dedup_sources = [
        ctx.native_root / "data_plane" / "storage" / "dedup.cpp",
        ctx.native_root / "data_plane" / "storage" / "dedup.h",
    ]
    dedup_present = all(path.exists() for path in dedup_sources)
    key = _unique("fn_compress")
    payload = ("A" * 4096).encode()
    put = ctx.kv_put(key, payload)
    if not _ok(put) and "value too large" in str(put.get("err", "")):
        return skip_result(
            "当前 SLAB_SLOT_SIZE 无法容纳 4096 字节压缩探针，需以 SLAB_SLOT_SIZE>=4096 重启后验证",
            details={"compress_stats": before, "put": put, "dedup_sources_present": dedup_present},
        )
    _require_ok(put, "RPC_KV_PUT compress probe")
    demote = ctx.rpc_json("RPC_TIER_DEMOTE", key.encode() + b"\x00hdd")
    _require_ok(demote, "RPC_TIER_DEMOTE hdd")
    after = ctx.rpc_json("RPC_COMPRESS_STATS")
    _require_ok(after, "RPC_COMPRESS_STATS after")
    before_objects = int(before.get("objects", 0) or 0)
    after_objects = int(after.get("objects", 0) or 0)
    before_saved = int(before.get("saved_bytes", 0) or 0)
    after_saved = int(after.get("saved_bytes", 0) or 0)
    if after_objects > before_objects or after_saved > before_saved:
        return pass_result(
            f"压缩统计增加: objects {before_objects}->{after_objects}, saved_bytes {before_saved}->{after_saved}",
            f"dedup.cpp/dedup.h 存在且纳入 nr_storage 构建口径: {dedup_present}",
            details={"before": before, "put": put, "demote": demote, "after": after, "dedup_present": dedup_present},
            completion="部分完成",
        )
    return fail_result(
        "demote 到 HDD 后压缩统计未增加",
        details={"before": before, "put": put, "demote": demote, "after": after, "dedup_present": dedup_present},
        completion="部分完成",
    )


def storage_fn5(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    path, text = ctx.data_plane_log(str(cluster.get("self", "")))
    if path and "IoScheduler init fg=" in text and " bg=" in text:
        return pass_result(
            f"数据面日志包含 IoScheduler 前台/后台队列初始化: {path}",
            details={"cluster": cluster, "log": str(path)},
        )
    return fail_result(
        "未找到 IoScheduler init fg=... bg=... 日志证据",
        details={"cluster": cluster, "log": str(path) if path else None},
    )


def storage_fn6(ctx: FnContext) -> CheckResult:
    reset = ctx.rpc_json("RPC_SIM_CAPTURE_RESET")
    _require_ok(reset, "RPC_SIM_CAPTURE_RESET")
    sim = ctx.rpc_json("RPC_SIM_RUN", "entities=1000&events=2000&threads=2&capture_every_n=10", timeout=10.0)
    _require_ok(sim, "RPC_SIM_RUN")
    time.sleep(0.4)
    stats = ctx.rpc_json("RPC_SIM_CAPTURE_STATS")
    _require_ok(stats, "RPC_SIM_CAPTURE_STATS")
    captured = int(sim.get("captured_events", 0) or 0)
    pushed = int(stats.get("pushed_events", 0) or 0)
    flushed = int(stats.get("flushed_events", 0) or 0)
    if captured > 0 and pushed > 0 and flushed > 0:
        return pass_result(
            f"仿真采集成功: captured={captured} pushed={pushed} flushed={flushed}",
            details={"reset": reset, "sim": sim, "capture_stats": stats},
        )
    return fail_result(
        f"仿真采集计数不足: captured={captured} pushed={pushed} flushed={flushed}",
        details={"reset": reset, "sim": sim, "capture_stats": stats},
    )


def rdma_fn1(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    path, text = ctx.data_plane_log(str(cluster.get("self", "")))
    has_qp = bool(re.search(r"created .* QPs", text))
    has_tcp = "TcpFallback listen" in text or "TcpFallback connected" in text
    if path and has_qp and has_tcp and _positive_int(cluster.get("peer_num_qp")):
        return pass_result(
            f"日志包含 RDMA QP 和 TCP fallback/OOB 证据: {path}",
            f"peer_num_qp={cluster.get('peer_num_qp')} peer_alive={cluster.get('peer_alive')}",
            details={"cluster": cluster, "log": str(path), "has_qp": has_qp, "has_tcp": has_tcp},
        )
    return fail_result(
        "缺少 RDMA QP、TCP fallback 或 peer_num_qp 证据",
        details={"cluster": cluster, "log": str(path) if path else None, "has_qp": has_qp, "has_tcp": has_tcp},
    )


def rdma_fn2(ctx: FnContext) -> CheckResult:
    items = [(f"{_unique('fn_batch')}_{i}", f"batch-value-{i}") for i in range(4)]
    batch = ctx.batch_put(items)
    if _ok(batch) and int(batch.get("ok_n", -1)) == len(items):
        cluster = ctx.cluster_status()
        path, text = ctx.data_plane_log(str(cluster.get("self", "")))
        log_found = bool(path and "BatchAggregator started" in text)
        return pass_result(
            f"RPC_KV_PUT_BATCH 成功: ok_n={batch.get('ok_n')}/{len(items)}",
            f"BatchAggregator 启动日志存在: {log_found}",
            details={"batch": batch, "log": str(path) if path else None, "log_found": log_found},
        )
    return fail_result("RPC_KV_PUT_BATCH 未完成全部批量写入", details={"batch": batch})


def rdma_fn3(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    path, text = ctx.data_plane_log(str(cluster.get("self", "")))
    has_qos = bool(path and "QosSched ready" in text)
    hi = ctx.kv_put(_unique("fn_qos_hi"), "hi-priority", "RPC_KV_PUT_HI")
    lo = ctx.kv_put(_unique("fn_qos_lo"), "lo-priority", "RPC_KV_PUT_LO")
    if _ok(hi) and _ok(lo) and has_qos:
        return pass_result(
            f"高低优先级 PUT 均成功，QosSched 日志存在: {path}",
            details={"hi": hi, "lo": lo, "log": str(path) if path else None},
        )
    return fail_result(
        "QoS 日志缺失或高低优先级 PUT 失败",
        details={"hi": hi, "lo": lo, "log": str(path) if path else None, "has_qos": has_qos},
    )


def rdma_fn4(ctx: FnContext) -> CheckResult:
    return waived_result(
        "当前环境未确认 GPU、CUDA 与 GPU Direct RDMA 可用，按需求文档暂时 WAIVED",
        details={
            "required_for_full_acceptance": [
                "可用 GPU",
                "CUDA runtime/driver",
                "GPU Direct RDMA 或项目定义等效直通路径",
            ]
        },
    )


def rdma_fn5(ctx: FnContext) -> CheckResult:
    counts: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for i in range(32):
        key = f"fn_route_{i}"
        route = ctx.rpc_json("RPC_ROUTE_QUERY", key)
        _require_ok(route, f"RPC_ROUTE_QUERY {key}")
        primary = str(route.get("primary") or "")
        if not primary:
            return fail_result("route 返回缺少 primary", details={"route": route})
        counts[primary] = counts.get(primary, 0) + 1
        items.append(route)
    if len(counts) >= 2:
        empty_replica = sum(1 for item in items if not item.get("replica"))
        return pass_result(
            f"32 个 key 路由查询成功，primary 分布: {counts}",
            f"replica 为空的样本数={empty_replica}，当前 ObjectRouter 在副本 hash 命中 primary 时会置空",
            details={"counts": counts, "items": items, "empty_replica": empty_replica},
        )
    return fail_result(
        f"路由查询可用但 primary 未覆盖多个节点: {counts}",
        details={"counts": counts, "items": items},
    )


def mempool_fn1(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    _require_peer_if_needed(ctx, cluster)
    key = _unique("fn_zero_copy")
    put = ctx.kv_put(key, "rdma-zero-copy-probe")
    _require_ok(put, "RPC_KV_PUT")
    if "repl_ns" in put and not bool(put.get("degraded", False)):
        return pass_result(
            f"PUT ok 且 repl_ns={put.get('repl_ns')} degraded={put.get('degraded')}",
            f"peer_slab_base={cluster.get('peer_slab_base')} peer_slab_rkey={cluster.get('peer_slab_rkey')}",
            details={"cluster": cluster, "put": put},
        )
    return fail_result(
        "PUT 未返回完整 RDMA 复制证据，或处于 degraded 写入",
        details={"cluster": cluster, "put": put},
    )


def mempool_fn2(ctx: FnContext) -> CheckResult:
    key = _unique("fn_pool_api")
    value = "distributed-pool-api-value"
    put = ctx.kv_put(key, value)
    _require_ok(put, "RPC_KV_PUT")
    got = ctx.kv_get(key)
    _require_ok(got, "RPC_KV_GET")
    if str(got.get("val", "")) == value:
        return pass_result(
            f"PUT/GET 闭环成功: key={key} hit={got.get('hit')} size={got.get('size')}",
            details={"put": put, "get": got},
        )
    return fail_result("GET 内容与 PUT 不一致", details={"put": put, "get": got, "expected": value})


def mempool_fn3(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    _require_peer_if_needed(ctx, cluster)
    fields_ok = (
        _positive_int(cluster.get("peer_slab_base"))
        and _positive_int(cluster.get("peer_slab_rkey"))
        and _positive_int(cluster.get("peer_num_qp"))
    )
    if fields_ok:
        return pass_result(
            f"peer slab 命名元数据有效: base={cluster.get('peer_slab_base')} rkey={cluster.get('peer_slab_rkey')} qps={cluster.get('peer_num_qp')}",
            details={"cluster": cluster},
        )
    return fail_result("peer slab base/rkey/qp 字段无效", details={"cluster": cluster})


def mempool_fn4(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    path, text = ctx.data_plane_log(str(cluster.get("self", "")))
    has_tier_log = bool(path and "TierEngine init" in text)
    key = _unique("fn_hot_migrate")
    put = ctx.kv_put(key, "hot-migration-payload")
    _require_ok(put, "RPC_KV_PUT")
    demote = ctx.rpc_json("RPC_TIER_DEMOTE", key.encode() + b"\x00nvme")
    _require_ok(demote, "RPC_TIER_DEMOTE nvme")
    got = ctx.kv_get(key)
    _require_ok(got, "RPC_KV_GET after demote")
    hit = str(got.get("hit", ""))
    if has_tier_log and "nvme" in hit:
        return pass_result(
            f"当前可观测热数据迁移闭环成功: demote->nvme, GET hit={hit}",
            f"TierEngine 初始化日志存在: {path}",
            details={"put": put, "demote": demote, "get": got, "log": str(path) if path else None},
            completion="部分完成",
        )
    return fail_result(
        "TierEngine 日志缺失或 demote 后 GET 未触发 nvme_promote",
        details={"put": put, "demote": demote, "get": got, "log": str(path) if path else None, "has_tier_log": has_tier_log},
        completion="部分完成",
    )


def mempool_fn5(ctx: FnContext) -> CheckResult:
    tenant = 1000 + (int(time.time()) % 100000)
    pool = "default/slab1k"
    key = _unique("fn_iso")
    deny0 = ctx.rpc_json("RPC_ISO_DENY", f"{tenant} {pool}")
    _require_ok(deny0, "RPC_ISO_DENY initial")
    denied1 = ctx.kv_put_tenant(tenant, key, "denied-before-allow")
    allow = ctx.rpc_json("RPC_ISO_ALLOW", f"{tenant} {pool}")
    _require_ok(allow, "RPC_ISO_ALLOW")
    allowed = ctx.kv_put_tenant(tenant, key, "allowed-value")
    get_allowed = ctx.kv_get(key, tenant)
    deny2 = ctx.rpc_json("RPC_ISO_DENY", f"{tenant} {pool}")
    _require_ok(deny2, "RPC_ISO_DENY final")
    denied2 = ctx.kv_put_tenant(tenant, key + "_again", "denied-after-revoke")
    if (
        denied1.get("ok") is False
        and allowed.get("ok") is True
        and get_allowed.get("ok") is True
        and denied2.get("ok") is False
    ):
        return pass_result(
            f"tenant={tenant} 完成拒绝->允许->读取->撤销->拒绝闭环",
            details={
                "deny0": deny0,
                "denied_before": denied1,
                "allow": allow,
                "allowed": allowed,
                "get_allowed": get_allowed,
                "deny_final": deny2,
                "denied_after": denied2,
            },
        )
    return fail_result(
        "租户隔离拒/允/拒闭环不成立",
        details={
            "deny0": deny0,
            "denied_before": denied1,
            "allow": allow,
            "allowed": allowed,
            "get_allowed": get_allowed,
            "deny_final": deny2,
            "denied_after": denied2,
        },
    )


def _ha_active_drill(ctx: FnContext, cluster: dict[str, Any]) -> CheckResult | None:
    peer_ssh = os.environ.get("PEER_SSH") or os.environ.get("NR_PEER_SSH")
    peer_dp_path = os.environ.get("PEER_DP_PATH") or os.environ.get("NR_PEER_DP_PATH")
    peer_start_cmd = os.environ.get("PEER_START_CMD") or os.environ.get("NR_PEER_START_CMD")
    if not ctx.allow_destructive:
        return None
    if not peer_ssh or not peer_dp_path:
        raise SkipCheck("ALLOW_DESTRUCTIVE=1 但未提供 PEER_SSH/PEER_DP_PATH")
    before = int(cluster.get("degraded_puts", 0) or 0)
    kill_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=no",
                peer_ssh, f"pkill -9 -f '{peer_dp_path}'"]
    kill = ctx.run_cmd(kill_cmd, timeout=8.0)
    time.sleep(4)
    mid = ctx.cluster_status()
    put = ctx.kv_put(_unique("fn_ha_degraded"), "during-outage")
    after_status = ctx.cluster_status()
    after = int(after_status.get("degraded_puts", 0) or 0)
    restore = None
    if peer_start_cmd:
        restore_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", peer_ssh, peer_start_cmd]
        restore = ctx.run_cmd(restore_cmd, timeout=12.0)
    if mid.get("peer_alive") is False and put.get("degraded") is True and after > before:
        return pass_result(
            f"主动故障演练成功: peer_alive=false, degraded_puts {before}->{after}",
            details={
                "kill_rc": kill.returncode,
                "mid": mid,
                "put": put,
                "after": after_status,
                "restore_rc": restore.returncode if restore else None,
            },
        )
    return fail_result(
        "主动故障演练未观测到预期降级写入",
        details={
            "kill_rc": kill.returncode,
            "mid": mid,
            "put": put,
            "after": after_status,
            "restore_rc": restore.returncode if restore else None,
        },
    )


def mempool_fn6(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    active = _ha_active_drill(ctx, cluster)
    if active:
        return active
    has_fields = all(name in cluster for name in ("peer_alive", "degraded_puts", "degraded_bytes"))
    if has_fields:
        return pass_result(
            f"HA 字段完备: peer_alive={cluster.get('peer_alive')} degraded_puts={cluster.get('degraded_puts')} degraded_bytes={cluster.get('degraded_bytes')}",
            "默认未执行主动 kill peer；完整演练需 ALLOW_DESTRUCTIVE=1 且提供 PEER_SSH/PEER_DP_PATH",
            details={"cluster": cluster},
            completion="部分完成",
        )
    return fail_result("RPC_CLUSTER_STATUS 缺少 HA 关键字段", details={"cluster": cluster})


CHECKS: dict[str, Callable[[FnContext], CheckResult]] = {
    name: obj
    for name, obj in globals().items()
    if callable(obj) and re.match(r"^(storage|rdma|mempool)_fn\d+$", name)
}


def run_check(name: str, ctx: FnContext) -> CheckResult:
    check = CHECKS.get(name)
    if not check:
        return fail_result(f"未找到检查函数: {name}")
    return check(ctx)
