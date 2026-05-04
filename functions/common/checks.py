from __future__ import annotations

import os
import re
import json
import shlex
import struct
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
    before = ctx.rpc_json("RPC_TIER_STATS")
    fields = ("dram", "nvme", "hdd")
    if not (_ok(before) and all(name in before for name in fields)):
        return fail_result("RPC_TIER_STATS 缺少 ok 或层级字段", details={"tier_stats": before})

    nvme_key = _unique("fn_storage_iface_nvme")
    nvme_val = "nvme-interface-probe"
    nvme_put = ctx.kv_put(nvme_key, nvme_val)
    _require_ok(nvme_put, "RPC_KV_PUT nvme probe")
    nvme_demote = ctx.rpc_json("RPC_TIER_DEMOTE", nvme_key.encode() + b"\x00nvme")
    _require_ok(nvme_demote, "RPC_TIER_DEMOTE nvme")
    after_nvme_demote = ctx.rpc_json("RPC_TIER_STATS")
    _require_ok(after_nvme_demote, "RPC_TIER_STATS after nvme demote")
    nvme_get = ctx.kv_get(nvme_key)
    _require_ok(nvme_get, "RPC_KV_GET nvme probe")

    hdd_key = _unique("fn_storage_iface_hdd")
    hdd_val = "hdd-interface-probe"
    hdd_put = ctx.kv_put(hdd_key, hdd_val)
    _require_ok(hdd_put, "RPC_KV_PUT hdd probe")
    hdd_demote = ctx.rpc_json("RPC_TIER_DEMOTE", hdd_key.encode() + b"\x00hdd")
    _require_ok(hdd_demote, "RPC_TIER_DEMOTE hdd")
    after_hdd_demote = ctx.rpc_json("RPC_TIER_STATS")
    _require_ok(after_hdd_demote, "RPC_TIER_STATS after hdd demote")
    hdd_get = ctx.kv_get(hdd_key)
    _require_ok(hdd_get, "RPC_KV_GET hdd probe")

    nvme_hit = str(nvme_get.get("hit", ""))
    hdd_hit = str(hdd_get.get("hit", ""))
    if "nvme" not in nvme_hit or str(nvme_get.get("val", "")) != nvme_val:
        return fail_result(
            f"NVMe 统一访问闭环失败: hit={nvme_hit}",
            details={
                "before": before,
                "put": nvme_put,
                "demote": nvme_demote,
                "stats_after_demote": after_nvme_demote,
                "get": nvme_get,
            },
        )
    if "hdd" not in hdd_hit or str(hdd_get.get("val", "")) != hdd_val:
        return fail_result(
            f"HDD 统一访问闭环失败: hit={hdd_hit}",
            details={
                "before": before,
                "put": hdd_put,
                "demote": hdd_demote,
                "stats_after_demote": after_hdd_demote,
                "get": hdd_get,
            },
        )

    return pass_result(
        "RPC_TIER_STATS 暴露 dram/nvme/hdd 统一层级字段",
        f"NVMe 闭环成功: PUT -> RPC_TIER_DEMOTE(nvme) -> GET hit={nvme_hit}",
        f"HDD 闭环成功: PUT -> RPC_TIER_DEMOTE(hdd) -> GET hit={hdd_hit}",
        details={
            "before": before,
            "nvme": {
                "put": nvme_put,
                "demote": nvme_demote,
                "stats_after_demote": after_nvme_demote,
                "get": nvme_get,
            },
            "hdd": {
                "put": hdd_put,
                "demote": hdd_demote,
                "stats_after_demote": after_hdd_demote,
                "get": hdd_get,
            },
        },
    )


def storage_fn2(ctx: FnContext) -> CheckResult:
    manual_key = _unique("fn_storage_tier_manual")
    manual_value = "tiering_probe_payload"
    manual_put = ctx.kv_put(manual_key, manual_value)
    _require_ok(manual_put, "RPC_KV_PUT manual")
    manual_demote = ctx.rpc_json("RPC_TIER_DEMOTE", manual_key.encode() + b"\x00nvme")
    _require_ok(manual_demote, "RPC_TIER_DEMOTE manual")
    manual_get = ctx.kv_get(manual_key)
    _require_ok(manual_get, "RPC_KV_GET after manual demote")
    manual_hit = str(manual_get.get("hit", ""))
    if "nvme" not in manual_hit or str(manual_get.get("val", "")) != manual_value:
        return fail_result(
            f"手动 demote 成功但 GET 未显示 nvme 命中或内容不一致: hit={manual_hit}",
            details={"put": manual_put, "demote": manual_demote, "get": manual_get},
        )

    auto_cold_key = _unique("fn_storage_tier_cold")
    auto_hot_key = _unique("fn_storage_tier_hot")
    cold_value = "auto-cold-tiering-payload"
    hot_value = "auto-hot-tiering-payload"
    cold_put = ctx.kv_put(auto_cold_key, cold_value)
    hot_put = ctx.kv_put(auto_hot_key, hot_value)
    _require_ok(cold_put, "RPC_KV_PUT auto cold")
    _require_ok(hot_put, "RPC_KV_PUT auto hot")

    wait_s = float(os.environ.get("FN2_AUTO_WAIT_SECONDS", "16"))
    interval_s = float(os.environ.get("FN2_HOT_ACCESS_INTERVAL_SECONDS", "1"))
    deadline = time.time() + wait_s
    hot_hits: list[dict[str, Any]] = []
    stats_samples: list[dict[str, Any]] = []
    while time.time() < deadline:
        hot_get = ctx.kv_get(auto_hot_key)
        _require_ok(hot_get, "RPC_KV_GET auto hot keepalive")
        hot_hits.append(hot_get)
        stats_probe = ctx.rpc_json("RPC_TIER_STATS")
        _require_ok(stats_probe, "RPC_TIER_STATS auto probe")
        stats_samples.append(stats_probe)
        probe_events = stats_probe.get("events") or []
        if any(
            item.get("key") == auto_cold_key and item.get("to") == "nvme"
            for item in probe_events
        ):
            break
        time.sleep(interval_s)

    stats_after_wait = ctx.rpc_json("RPC_TIER_STATS")
    _require_ok(stats_after_wait, "RPC_TIER_STATS after auto wait")
    cold_get = ctx.kv_get(auto_cold_key)
    _require_ok(cold_get, "RPC_KV_GET auto cold after wait")
    hot_final = ctx.kv_get(auto_hot_key)
    _require_ok(hot_final, "RPC_KV_GET auto hot final")

    cold_hit = str(cold_get.get("hit", ""))
    hot_promoted = [
        item for item in hot_hits + [hot_final]
        if "promote" in str(item.get("hit", ""))
    ]
    events = stats_after_wait.get("events") or []
    cold_demote_event = [
        item for item in events
        if item.get("key") == auto_cold_key and item.get("to") == "nvme"
    ]
    hot_demote_event = [
        item for item in events
        if item.get("key") == auto_hot_key and item.get("to") in {"nvme", "hdd"}
    ]
    if "nvme" not in cold_hit or str(cold_get.get("val", "")) != cold_value:
        return fail_result(
            f"自动冷热分离未将冷对象下沉到 NVMe: cold_hit={cold_hit}",
            details={
                "manual": {"put": manual_put, "demote": manual_demote, "get": manual_get},
                "auto": {
                    "cold_put": cold_put,
                    "hot_put": hot_put,
                    "hot_hits": hot_hits,
                    "stats_samples": stats_samples,
                    "stats_after_wait": stats_after_wait,
                    "cold_get": cold_get,
                    "hot_final": hot_final,
                    "wait_s": wait_s,
                },
            },
        )
    if hot_promoted or hot_demote_event:
        return fail_result(
            "热对象在持续访问期间发生下沉或读时提升，不符合热数据保留预期",
            details={
                "manual": {"put": manual_put, "demote": manual_demote, "get": manual_get},
                "auto": {
                    "cold_put": cold_put,
                    "hot_put": hot_put,
                    "hot_hits": hot_hits,
                    "stats_samples": stats_samples,
                    "stats_after_wait": stats_after_wait,
                    "cold_get": cold_get,
                    "hot_final": hot_final,
                    "hot_promoted": hot_promoted,
                    "hot_demote_event": hot_demote_event,
                    "wait_s": wait_s,
                },
            },
        )

    return pass_result(
        f"手动冷热迁移闭环成功: {manual_key} demote->nvme, GET hit={manual_hit}",
        f"自动冷热分离成功: 冷对象 {auto_cold_key} 等待 {wait_s:.1f}s 后 GET hit={cold_hit}",
        f"热对象 {auto_hot_key} 持续访问期间未发生下沉，最终 hit={hot_final.get('hit')}",
        details={
            "manual": {"put": manual_put, "demote": manual_demote, "get": manual_get},
            "auto": {
                "cold_put": cold_put,
                "hot_put": hot_put,
                "hot_hits": hot_hits,
                "stats_samples": stats_samples,
                "stats_after_wait": stats_after_wait,
                "cold_get": cold_get,
                "hot_final": hot_final,
                "cold_demote_event": cold_demote_event,
                "hot_demote_event": hot_demote_event,
                "wait_s": wait_s,
                "interval_s": interval_s,
            },
        },
    )


def storage_fn3(ctx: FnContext) -> CheckResult:
    def counter(data: dict[str, Any], name: str) -> int:
        try:
            return int(data.get(name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    before = ctx.rpc_json("RPC_PREFETCH_STATS", _unique("fn_prefetch_baseline_key"))
    _require_ok(before, "RPC_PREFETCH_STATS before")

    stride_prefix = _unique("fn_prefetch_stride_") + "_"
    stride_items = [(f"{stride_prefix}{i}", f"stride-value-{i}") for i in range(8)]
    for key, val in stride_items:
        _require_ok(ctx.kv_put(key, val), f"PUT stride {key}")
    stride_expected_key, stride_expected_val = stride_items[4]
    stride_demote = ctx.rpc_json("RPC_TIER_DEMOTE", stride_expected_key.encode() + b"\x00nvme")
    _require_ok(stride_demote, "RPC_TIER_DEMOTE stride expected")
    for key, _ in stride_items[:4]:
        _require_ok(ctx.kv_get(key), f"GET stride train {key}")
    stride_stats = ctx.rpc_json("RPC_PREFETCH_STATS", stride_items[3][0])
    _require_ok(stride_stats, "RPC_PREFETCH_STATS stride")
    stride_predicted = stride_stats.get("predicted") or []
    stride_get = ctx.kv_get(stride_expected_key)
    _require_ok(stride_get, "RPC_KV_GET stride prefetched")
    stride_after = ctx.rpc_json("RPC_PREFETCH_STATS", stride_expected_key)
    _require_ok(stride_after, "RPC_PREFETCH_STATS stride after")
    if stride_expected_key not in stride_predicted:
        return fail_result(
            "stride 预测未包含下一顺序 key",
            details={
                "before": before,
                "stride_stats": stride_stats,
                "expected": stride_expected_key,
                "predicted": stride_predicted,
            },
        )
    if str(stride_get.get("hit", "")) != "local" or str(stride_get.get("val", "")) != stride_expected_val:
        return fail_result(
            f"stride 预测对象未被提前加载到 DRAM: hit={stride_get.get('hit')}",
            details={
                "before": before,
                "demote": stride_demote,
                "stride_stats": stride_stats,
                "get": stride_get,
                "after": stride_after,
            },
        )
    if counter(stride_after, "prefetch_loaded") <= counter(before, "prefetch_loaded"):
        return fail_result(
            "stride 预测未增加 prefetch_loaded 统计",
            details={"before": before, "after": stride_after, "get": stride_get},
        )
    if counter(stride_after, "prefetch_hits") <= counter(before, "prefetch_hits"):
        return fail_result(
            "stride 预测对象后续 GET 未计入 prefetch_hits",
            details={"before": before, "after": stride_after, "get": stride_get},
        )

    markov_base = _unique("fn_prefetch_markov") + "_"
    markov_a = markov_base + "Akey"
    markov_b = markov_base + "Bkey"
    markov_a_val = "markov-a-value"
    markov_b_val = "markov-b-value"
    _require_ok(ctx.kv_put(markov_a, markov_a_val), "PUT markov A")
    _require_ok(ctx.kv_put(markov_b, markov_b_val), "PUT markov B")
    for _ in range(3):
        _require_ok(ctx.kv_get(markov_a), "GET markov train A")
        _require_ok(ctx.kv_get(markov_b), "GET markov train B")
    markov_demote = ctx.rpc_json("RPC_TIER_DEMOTE", markov_b.encode() + b"\x00nvme")
    _require_ok(markov_demote, "RPC_TIER_DEMOTE markov B")
    markov_mid = ctx.rpc_json("RPC_PREFETCH_STATS", markov_a)
    _require_ok(markov_mid, "RPC_PREFETCH_STATS markov before trigger")
    markov_predicted = markov_mid.get("predicted") or []
    _require_ok(ctx.kv_get(markov_a), "GET markov trigger A")
    markov_get_b = ctx.kv_get(markov_b)
    _require_ok(markov_get_b, "RPC_KV_GET markov prefetched B")
    markov_after = ctx.rpc_json("RPC_PREFETCH_STATS", markov_a)
    _require_ok(markov_after, "RPC_PREFETCH_STATS markov after")
    if markov_b not in markov_predicted:
        return fail_result(
            "Markov 预测未包含高频 next key",
            details={
                "markov_stats": markov_mid,
                "expected": markov_b,
                "predicted": markov_predicted,
            },
        )
    if str(markov_get_b.get("hit", "")) != "local" or str(markov_get_b.get("val", "")) != markov_b_val:
        return fail_result(
            f"Markov 预测对象未被提前加载到 DRAM: hit={markov_get_b.get('hit')}",
            details={
                "demote": markov_demote,
                "markov_stats": markov_mid,
                "get_b": markov_get_b,
                "after": markov_after,
            },
        )
    if counter(markov_after, "prefetch_loaded") <= counter(stride_after, "prefetch_loaded"):
        return fail_result(
            "Markov 预测未增加 prefetch_loaded 统计",
            details={"before": stride_after, "after": markov_after, "get_b": markov_get_b},
        )
    if counter(markov_after, "prefetch_hits") <= counter(stride_after, "prefetch_hits"):
        return fail_result(
            "Markov 预测对象后续 GET 未计入 prefetch_hits",
            details={"before": stride_after, "after": markov_after, "get_b": markov_get_b},
        )

    return pass_result(
        f"stride 预取执行成功: predicted={stride_expected_key}, GET hit={stride_get.get('hit')}",
        f"Markov 预取执行成功: predicted={markov_b}, GET hit={markov_get_b.get('hit')}",
        f"预取统计增加: loaded {counter(before, 'prefetch_loaded')}->{counter(markov_after, 'prefetch_loaded')}, hits {counter(before, 'prefetch_hits')}->{counter(markov_after, 'prefetch_hits')}",
        details={
            "before": before,
            "stride": {
                "items": stride_items,
                "demote": stride_demote,
                "stats": stride_stats,
                "get": stride_get,
                "after": stride_after,
            },
            "markov": {
                "a": markov_a,
                "b": markov_b,
                "demote": markov_demote,
                "stats": markov_mid,
                "get_b": markov_get_b,
                "after": markov_after,
            },
        },
    )


def storage_fn4(ctx: FnContext) -> CheckResult:
    before_compress = ctx.rpc_json("RPC_COMPRESS_STATS")
    _require_ok(before_compress, "RPC_COMPRESS_STATS before")
    before_dedup = ctx.rpc_json("RPC_DEDUP_STATS")
    _require_ok(before_dedup, "RPC_DEDUP_STATS before")

    key_a = _unique("fn_compress_dedup_a")
    key_b = _unique("fn_compress_dedup_b")
    payload = ("A" * 4096).encode()
    put = ctx.kv_put(key_a, payload)
    if not _ok(put) and "value too large" in str(put.get("err", "")):
        return skip_result(
            "当前 SLAB_SLOT_SIZE 无法容纳 4096 字节压缩探针，需以 SLAB_SLOT_SIZE>=4096 重启后验证",
            details={"compress_stats": before_compress, "dedup_stats": before_dedup, "put": put},
        )
    _require_ok(put, "RPC_KV_PUT compress/dedup probe A")
    put_b = ctx.kv_put(key_b, payload)
    _require_ok(put_b, "RPC_KV_PUT compress/dedup probe B")

    demote_a = ctx.rpc_json("RPC_TIER_DEMOTE", key_a.encode() + b"\x00hdd")
    _require_ok(demote_a, "RPC_TIER_DEMOTE hdd A")
    after_first_compress = ctx.rpc_json("RPC_COMPRESS_STATS")
    _require_ok(after_first_compress, "RPC_COMPRESS_STATS after first demote")

    demote_b = ctx.rpc_json("RPC_TIER_DEMOTE", key_b.encode() + b"\x00hdd")
    _require_ok(demote_b, "RPC_TIER_DEMOTE hdd B")
    after_compress = ctx.rpc_json("RPC_COMPRESS_STATS")
    _require_ok(after_compress, "RPC_COMPRESS_STATS after second demote")
    after_dedup = ctx.rpc_json("RPC_DEDUP_STATS")
    _require_ok(after_dedup, "RPC_DEDUP_STATS after")

    get_a = ctx.kv_get(key_a)
    _require_ok(get_a, "RPC_KV_GET hdd compressed/dedup A")
    get_b = ctx.kv_get(key_b)
    _require_ok(get_b, "RPC_KV_GET hdd compressed/dedup B")

    before_objects = int(before_compress.get("objects", 0) or 0)
    after_objects = int(after_compress.get("objects", 0) or 0)
    before_saved = int(before_compress.get("saved_bytes", 0) or 0)
    after_saved = int(after_compress.get("saved_bytes", 0) or 0)
    before_dups = int(before_dedup.get("duplicate_objects", 0) or 0)
    after_dups = int(after_dedup.get("duplicate_objects", 0) or 0)
    before_dedup_saved = int(before_dedup.get("saved_bytes", 0) or 0)
    after_dedup_saved = int(after_dedup.get("saved_bytes", 0) or 0)

    if not (after_objects > before_objects or after_saved > before_saved):
        return fail_result(
            "demote 到 HDD 后压缩统计未增加",
            details={
                "before_compress": before_compress,
                "after_first_compress": after_first_compress,
                "after_compress": after_compress,
                "before_dedup": before_dedup,
                "after_dedup": after_dedup,
                "put_a": put,
                "put_b": put_b,
                "demote_a": demote_a,
                "demote_b": demote_b,
                "get_a": get_a,
                "get_b": get_b,
            },
        )
    if not (after_dups > before_dups and after_dedup_saved > before_dedup_saved):
        return fail_result(
            "重复对象 demote 到 HDD 后去重统计未增加",
            details={
                "before_compress": before_compress,
                "after_first_compress": after_first_compress,
                "after_compress": after_compress,
                "before_dedup": before_dedup,
                "after_dedup": after_dedup,
                "put_a": put,
                "put_b": put_b,
                "demote_a": demote_a,
                "demote_b": demote_b,
                "get_a": get_a,
                "get_b": get_b,
            },
        )
    if "hdd" not in str(get_a.get("hit", "")) or "hdd" not in str(get_b.get("hit", "")):
        return fail_result(
            f"压缩/去重对象读回未显示 HDD 提升: hit_a={get_a.get('hit')} hit_b={get_b.get('hit')}",
            details={
                "before_compress": before_compress,
                "after_compress": after_compress,
                "before_dedup": before_dedup,
                "after_dedup": after_dedup,
                "get_a": get_a,
                "get_b": get_b,
            },
        )

    return pass_result(
        f"压缩统计增加: objects {before_objects}->{after_objects}, saved_bytes {before_saved}->{after_saved}",
        f"去重统计增加: duplicate_objects {before_dups}->{after_dups}, saved_bytes {before_dedup_saved}->{after_dedup_saved}",
        f"HDD 读回闭环成功: A hit={get_a.get('hit')}, B hit={get_b.get('hit')}",
        details={
            "before_compress": before_compress,
            "after_first_compress": after_first_compress,
            "after_compress": after_compress,
            "before_dedup": before_dedup,
            "after_dedup": after_dedup,
            "put_a": put,
            "put_b": put_b,
            "demote_a": demote_a,
            "demote_b": demote_b,
            "get_a": get_a,
            "get_b": get_b,
        },
    )


def storage_fn5(ctx: FnContext) -> CheckResult:
    def counter(data: dict[str, Any], name: str) -> int:
        try:
            return int(data.get(name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    path, text = ctx.data_plane_log(str(cluster.get("self", "")))
    if not (path and "IoScheduler init fg=" in text and " bg=" in text):
        return fail_result(
            "未找到 IoScheduler init fg=... bg=... 日志证据",
            details={"cluster": cluster, "log": str(path) if path else None},
        )

    before = ctx.rpc_json("RPC_IO_STATS")
    _require_ok(before, "RPC_IO_STATS before")

    fg_key = _unique("fn_io_fg_nvme")
    fg_value = "foreground-nvme-io-probe"
    fg_put = ctx.kv_put(fg_key, fg_value)
    _require_ok(fg_put, "RPC_KV_PUT fg probe")
    fg_demote = ctx.rpc_json("RPC_TIER_DEMOTE", fg_key.encode() + b"\x00nvme")
    _require_ok(fg_demote, "RPC_TIER_DEMOTE nvme fg")
    fg_get = ctx.kv_get(fg_key)
    _require_ok(fg_get, "RPC_KV_GET nvme fg")

    bg_key = _unique("fn_io_bg_hdd")
    bg_value = "background-hdd-io-probe"
    bg_put = ctx.kv_put(bg_key, bg_value)
    _require_ok(bg_put, "RPC_KV_PUT bg probe")
    bg_demote = ctx.rpc_json("RPC_TIER_DEMOTE", bg_key.encode() + b"\x00hdd")
    _require_ok(bg_demote, "RPC_TIER_DEMOTE hdd bg")
    bg_get = ctx.kv_get(bg_key)
    _require_ok(bg_get, "RPC_KV_GET hdd bg")

    after = ctx.rpc_json("RPC_IO_STATS")
    _require_ok(after, "RPC_IO_STATS after")

    fg_write_delta = counter(after, "fg_write_ops") - counter(before, "fg_write_ops")
    fg_read_delta = counter(after, "fg_read_ops") - counter(before, "fg_read_ops")
    bg_write_delta = counter(after, "bg_write_ops") - counter(before, "bg_write_ops")
    bg_read_delta = counter(after, "bg_read_ops") - counter(before, "bg_read_ops")
    if fg_write_delta <= 0 or fg_read_delta <= 0:
        return fail_result(
            "NVMe 前台 I/O 路径未产生 FG read/write 计数",
            details={
                "cluster": cluster,
                "log": str(path),
                "before": before,
                "after": after,
                "fg": {"put": fg_put, "demote": fg_demote, "get": fg_get},
                "bg": {"put": bg_put, "demote": bg_demote, "get": bg_get},
            },
        )
    if bg_write_delta <= 0 or bg_read_delta <= 0:
        return fail_result(
            "HDD 后台 I/O 路径未产生 BG read/write 计数",
            details={
                "cluster": cluster,
                "log": str(path),
                "before": before,
                "after": after,
                "fg": {"put": fg_put, "demote": fg_demote, "get": fg_get},
                "bg": {"put": bg_put, "demote": bg_demote, "get": bg_get},
            },
        )
    if "nvme" not in str(fg_get.get("hit", "")) or str(fg_get.get("val", "")) != fg_value:
        return fail_result(
            f"前台 NVMe 对象读回异常: hit={fg_get.get('hit')}",
            details={"before": before, "after": after, "fg_get": fg_get},
        )
    if "hdd" not in str(bg_get.get("hit", "")) or str(bg_get.get("val", "")) != bg_value:
        return fail_result(
            f"后台 HDD 对象读回异常: hit={bg_get.get('hit')}",
            details={"before": before, "after": after, "bg_get": bg_get},
        )

    return pass_result(
        f"数据面日志包含 IoScheduler 前台/后台队列初始化: {path}",
        f"前台 NVMe I/O 计数增加: fg_write_ops +{fg_write_delta}, fg_read_ops +{fg_read_delta}",
        f"后台 HDD I/O 计数增加: bg_write_ops +{bg_write_delta}, bg_read_ops +{bg_read_delta}",
        details={
            "cluster": cluster,
            "log": str(path),
            "before": before,
            "after": after,
            "fg": {"put": fg_put, "demote": fg_demote, "get": fg_get},
            "bg": {"put": bg_put, "demote": bg_demote, "get": bg_get},
        },
    )


def storage_fn6(ctx: FnContext) -> CheckResult:
    def counter(data: dict[str, Any], name: str) -> int:
        try:
            return int(data.get(name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def parse_wal(path: Path) -> dict[str, Any]:
        blob = path.read_bytes()
        off = 0
        total = 0
        object_attr = 0
        interaction = 0
        bad = False
        header_size = 32
        while off + header_size <= len(blob):
            _ts, _entity, _peer, typ, blob_len, _reserved = struct.unpack_from("<QQQHHI", blob, off)
            off += header_size
            if off + blob_len > len(blob):
                bad = True
                break
            off += blob_len
            total += 1
            if typ == 1:
                object_attr += 1
            elif typ == 2:
                interaction += 1
        if off != len(blob):
            bad = True
        return {
            "bytes": len(blob),
            "events": total,
            "object_attr_events": object_attr,
            "interaction_events": interaction,
            "truncated_or_bad": bad,
        }

    reset = ctx.rpc_json("RPC_SIM_CAPTURE_RESET")
    _require_ok(reset, "RPC_SIM_CAPTURE_RESET")
    sim = ctx.rpc_json("RPC_SIM_RUN", "entities=1000&events=2000&threads=2&capture_every_n=10", timeout=10.0)
    _require_ok(sim, "RPC_SIM_RUN")
    time.sleep(0.4)
    stats = ctx.rpc_json("RPC_SIM_CAPTURE_STATS")
    _require_ok(stats, "RPC_SIM_CAPTURE_STATS")
    captured = counter(sim, "captured_events")
    pushed = counter(stats, "pushed_events")
    flushed = counter(stats, "flushed_events")
    pushed_bytes = counter(stats, "pushed_bytes")
    flushed_bytes = counter(stats, "flushed_bytes")
    object_attr = counter(stats, "object_attr_events")
    interaction = counter(stats, "interaction_events")
    dropped = counter(stats, "dropped_events") + counter(sim, "captured_dropped")
    wal_path_raw = str(stats.get("wal_path", ""))
    wal_path = Path(wal_path_raw)
    if not wal_path_raw or not wal_path.exists():
        return fail_result(
            f"采集 WAL 文件不存在: {wal_path_raw}",
            details={"reset": reset, "sim": sim, "capture_stats": stats},
        )
    wal_scan = parse_wal(wal_path)
    if captured <= 0 or pushed <= 0 or flushed <= 0 or pushed_bytes <= 0 or flushed_bytes <= 0:
        return fail_result(
            f"仿真采集计数不足: captured={captured} pushed={pushed} flushed={flushed}",
            details={"reset": reset, "sim": sim, "capture_stats": stats, "wal_scan": wal_scan},
        )
    if dropped != 0:
        return fail_result(
            f"仿真采集发生丢弃: dropped={dropped}",
            details={"reset": reset, "sim": sim, "capture_stats": stats, "wal_scan": wal_scan},
        )
    if object_attr <= 0 or interaction <= 0:
        return fail_result(
            f"采集类型不完整: object_attr={object_attr} interaction={interaction}",
            details={"reset": reset, "sim": sim, "capture_stats": stats, "wal_scan": wal_scan},
        )
    if wal_scan["truncated_or_bad"] or wal_scan["object_attr_events"] <= 0 or wal_scan["interaction_events"] <= 0:
        return fail_result(
            "WAL 解析未同时包含 ObjectAttr 和 InteractionEvent",
            details={"reset": reset, "sim": sim, "capture_stats": stats, "wal_scan": wal_scan},
        )
    if wal_scan["bytes"] < flushed_bytes or wal_scan["events"] < flushed:
        return fail_result(
            "WAL 文件大小或事件数量小于 flush 统计",
            details={"reset": reset, "sim": sim, "capture_stats": stats, "wal_scan": wal_scan},
        )
    return pass_result(
        f"仿真采集成功: captured={captured} pushed={pushed} flushed={flushed}",
        f"多类型采集成功: ObjectAttr={object_attr}, InteractionEvent={interaction}",
        f"WAL 落盘成功: path={wal_path}, events={wal_scan['events']}, bytes={wal_scan['bytes']}",
        details={"reset": reset, "sim": sim, "capture_stats": stats, "wal_scan": wal_scan},
    )


def rdma_fn1(ctx: FnContext) -> CheckResult:
    def ns_stats(samples: list[int]) -> dict[str, Any]:
        def us(ns: int) -> float:
            return round(ns / 1000.0, 3)

        ordered = sorted(samples)
        if not ordered:
            return {
                "n": 0,
                "avg_ns": 0,
                "p50_ns": 0,
                "p95_ns": 0,
                "avg_us": 0.0,
                "p50_us": 0.0,
                "p95_us": 0.0,
            }
        p95_idx = min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))
        avg_ns = int(sum(ordered) / len(ordered))
        p50_ns = ordered[len(ordered) // 2]
        p95_ns = ordered[p95_idx]
        min_ns = ordered[0]
        max_ns = ordered[-1]
        return {
            "n": len(ordered),
            "avg_ns": avg_ns,
            "p50_ns": p50_ns,
            "p95_ns": p95_ns,
            "min_ns": min_ns,
            "max_ns": max_ns,
            "avg_us": us(avg_ns),
            "p50_us": us(p50_ns),
            "p95_us": us(p95_ns),
            "min_us": us(min_ns),
            "max_us": us(max_ns),
        }

    def run_put_series(kind: str, transport: str, count: int) -> dict[str, Any]:
        samples: list[int] = []
        responses: list[dict[str, Any]] = []
        degraded = 0
        prefix = "fn_rdmavtcp_" + transport
        for i in range(count):
            key = f"{_unique(prefix)}_{i}"
            value = f"{transport}-latency-probe-{i}"
            put = ctx.kv_put(key, value, kind)
            _require_ok(put, f"{kind} {i}")
            responses.append(put)
            if put.get("transport") != transport:
                raise FailCheck(f"{kind} 未走预期 transport={transport}: {put}")
            if bool(put.get("degraded", False)):
                degraded += 1
            try:
                samples.append(int(put.get("repl_ns", 0) or 0))
            except (TypeError, ValueError):
                samples.append(0)
        return {
            "kind": kind,
            "transport": transport,
            "degraded": degraded,
            "stats": ns_stats(samples),
            "responses": responses,
        }

    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    path, text = ctx.data_plane_log(str(cluster.get("self", "")))
    last_start = text.rfind("native_rdma_dp starting")
    recent_log = text[last_start:] if last_start >= 0 else text
    has_qp = bool(re.search(r"created .* QPs", recent_log))
    has_tcp = "TcpFallback listen" in recent_log or "TcpFallback connected" in recent_log
    has_oob = "OOB exchanged" in recent_log
    peer_alive = bool(cluster.get("peer_alive", False))
    peer_meta_ok = (
        _positive_int(cluster.get("peer_num_qp"))
        and _positive_int(cluster.get("peer_slab_base"))
        and _positive_int(cluster.get("peer_slab_rkey"))
    )
    details = {
        "cluster": cluster,
        "log": str(path) if path else None,
        "has_qp": has_qp,
        "has_tcp": has_tcp,
        "has_oob": has_oob,
        "peer_meta_ok": peer_meta_ok,
        "checked_recent_log_from_last_start": last_start >= 0,
    }
    if ctx.require_peer and not peer_alive:
        return skip_result(
            "REQUIRE_PEER=1 且 peer_alive=false，不能证明当前双节点 RDMA/TCP 通信层在线",
            details=details,
        )
    if path and has_qp and has_tcp and has_oob and peer_meta_ok:
        if not bool(cluster.get("tcp_data_ready", False)):
            return fail_result(
                "TCP data channel 未就绪，不能证明传统 TCP/IP 数据传输闭环",
                details=details,
            )
        if str(cluster.get("transport", "")) != "tcp":
            return fail_result(
                "FN-1 严格 TCP/IP 验收要求数据面以 NR_TRANSPORT=tcp 启动；当前未切换普通 PUT 路径",
                details=details,
            )
        if bool(cluster.get("async_repl", True)):
            return fail_result(
                "FN-1 RDMA/TCP 时延对比要求 NR_ASYNC_REPL=0，否则 RDMA repl_ns 只代表 post 延迟",
                details=details,
            )
        key = _unique("fn_tcp_transport")
        value = "tcp-transport-probe"
        tcp_put = ctx.kv_put(key, value, "RPC_KV_PUT")
        _require_ok(tcp_put, "RPC_KV_PUT transport=tcp")
        tcp_get_peer = ctx.rpc_json("RPC_TCP_GET_PEER", key)
        _require_ok(tcp_get_peer, "RPC_TCP_GET_PEER")
        details["tcp_put"] = tcp_put
        details["tcp_get_peer"] = tcp_get_peer
        if (
            tcp_put.get("transport") != "tcp"
            or bool(tcp_put.get("degraded", True))
            or tcp_get_peer.get("transport") != "tcp"
            or str(tcp_get_peer.get("val", "")) != value
        ):
            return fail_result(
                "TCP 数据面 PUT/peer GET 闭环失败",
                details=details,
            )
        compare_count = int(os.environ.get("FN1_COMPARE_OPS", "8"))
        if compare_count < 3:
            compare_count = 3
        rdma_series = run_put_series("RPC_KV_PUT_RDMA", "rdma", compare_count)
        tcp_series = run_put_series("RPC_KV_PUT", "tcp", compare_count)
        details["latency_compare"] = {
            "count": compare_count,
            "rdma": rdma_series,
            "tcp": tcp_series,
            "note": "repl_ns 为同步复制路径耗时；本项要求 NR_ASYNC_REPL=0。",
        }
        if rdma_series["degraded"] or tcp_series["degraded"]:
            return fail_result(
                "RDMA/TCP 时延对比存在 degraded 写入，不能作为有效对比证据",
                details=details,
            )
        return pass_result(
            f"最近一次数据面启动日志包含 RDMA QP、TcpFallback 和 OOB exchange 证据: {path}",
            f"peer_alive={peer_alive} peer_num_qp={cluster.get('peer_num_qp')} peer_slab_rkey={cluster.get('peer_slab_rkey')}",
            f"TCP 协议切换闭环成功: RPC_KV_PUT transport={tcp_put.get('transport')} -> RPC_TCP_GET_PEER size={tcp_get_peer.get('size')}",
            f"RDMA/TCP 复制时延对比: RDMA avg={rdma_series['stats']['avg_us']}us p95={rdma_series['stats']['p95_us']}us; TCP avg={tcp_series['stats']['avg_us']}us p95={tcp_series['stats']['p95_us']}us; samples={compare_count}",
            details=details,
        )
    return fail_result(
        "缺少最近一次启动的 RDMA QP、TcpFallback/OOB 或 peer 元数据证据",
        details=details,
    )


def rdma_fn2(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    path, text = ctx.data_plane_log(str(cluster.get("self", "")))
    last_start = text.rfind("native_rdma_dp starting")
    recent_log = text[last_start:] if last_start >= 0 else text
    has_batch = bool(path and "BatchAggregator started" in recent_log)
    has_qp = bool(re.search(r"created .* QPs", recent_log))
    has_oob = "OOB exchanged" in recent_log
    details: dict[str, Any] = {
        "cluster": cluster,
        "log": str(path) if path else None,
        "checked_recent_log_from_last_start": last_start >= 0,
        "has_batch_aggregator_started": has_batch,
        "has_qp": has_qp,
        "has_oob": has_oob,
    }
    if ctx.require_peer and not bool(cluster.get("peer_alive", False)):
        return skip_result(
            "REQUIRE_PEER=1 且 peer_alive=false，不能证明批量 RDMA 聚合传输到 xfusion4",
            details=details,
        )
    if not has_batch or not has_qp or not has_oob:
        return fail_result(
            "最近一次启动日志缺少 BatchAggregator、RDMA QP 或 OOB 初始化证据",
            details=details,
        )
    if bool(cluster.get("async_repl", True)):
        return fail_result(
            "FN-2 严格验收要求 NR_ASYNC_REPL=0，以便脚本确认批量 RDMA WRITE 完成后再读 peer",
            details=details,
        )
    if str(cluster.get("transport", "rdma")) == "tcp":
        return fail_result(
            "FN-2 聚合传输要求普通 RDMA 数据面启动，不应使用 NR_TRANSPORT=tcp",
            details=details,
        )
    if not bool(cluster.get("tcp_data_ready", False)):
        return fail_result(
            "peer 读回校验需要 TCP data channel 作为验证通道，当前 tcp_data_ready=false",
            details=details,
        )

    count = int(os.environ.get("FN2_BATCH_ITEMS", "8"))
    if count < 4:
        count = 4
    items = [(f"{_unique('fn_batch')}_{i}", f"batch-value-{i}") for i in range(count)]
    batch = ctx.batch_put(items)
    details["batch"] = batch
    if not (
        _ok(batch)
        and int(batch.get("ok_n", -1)) == len(items)
        and bool(batch.get("peer_alive", False))
        and int(batch.get("replicated_n", -1)) == len(items)
        and int(batch.get("degraded_n", -1)) == 0
        and int(batch.get("repl_failed_n", -1)) == 0
        and str(batch.get("transport", "")) == "rdma"
        and bool(batch.get("degraded", True)) is False
    ):
        return fail_result(
            "RPC_KV_PUT_BATCH 未证明全部小对象通过 RDMA 批量路径复制到 peer",
            details=details,
        )

    peer_gets: list[dict[str, Any]] = []
    peer_get_timeout = float(os.environ.get("FN2_PEER_GET_TIMEOUT_SECONDS", "3"))
    for key, value in items:
        expected = value.decode() if isinstance(value, bytes) else value
        got: dict[str, Any] = {}
        deadline = time.time() + peer_get_timeout
        while time.time() < deadline:
            got = ctx.rpc_json("RPC_TCP_GET_PEER", key)
            if _ok(got) and str(got.get("val", "")) == expected:
                break
            time.sleep(0.05)
        peer_gets.append(got)
        if not (_ok(got) and str(got.get("val", "")) == expected):
            details["peer_gets"] = peer_gets
            return fail_result(
                f"批量 RDMA 写入后 peer 读回失败: key={key}",
                details=details,
            )
    details["peer_gets"] = peer_gets
    return pass_result(
        f"RPC_KV_PUT_BATCH 成功: ok_n={batch.get('ok_n')}/{len(items)} replicated_n={batch.get('replicated_n')}/{len(items)}",
        f"批量 RDMA peer 读回成功: RPC_TCP_GET_PEER {len(peer_gets)}/{len(items)} 同值",
        f"最近一次启动日志包含 BatchAggregator/RDMA QP/OOB 证据: {path}",
        details=details,
    )


def rdma_fn3(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    path, text = ctx.data_plane_log(str(cluster.get("self", "")))
    last_start = text.rfind("native_rdma_dp starting")
    recent_log = text[last_start:] if last_start >= 0 else text
    has_qos = bool(path and "QosSched ready" in recent_log)
    has_qp = bool(re.search(r"created .* QPs", recent_log))
    has_oob = "OOB exchanged" in recent_log
    details: dict[str, Any] = {
        "cluster": cluster,
        "log": str(path) if path else None,
        "checked_recent_log_from_last_start": last_start >= 0,
        "has_qos": has_qos,
        "has_qp": has_qp,
        "has_oob": has_oob,
    }
    if ctx.require_peer and not bool(cluster.get("peer_alive", False)):
        return skip_result(
            "REQUIRE_PEER=1 且 peer_alive=false，不能证明高低优先级 RDMA 数据面在线",
            details=details,
        )
    if not has_qos or not has_qp or not has_oob:
        return fail_result(
            "最近一次启动日志缺少 QosSched、RDMA QP 或 OOB 初始化证据",
            details=details,
        )
    if bool(cluster.get("async_repl", True)):
        return fail_result(
            "FN-3 严格验收要求 NR_ASYNC_REPL=0，以便确认高低优先级 RDMA WRITE 完成后再读 peer",
            details=details,
        )
    if str(cluster.get("transport", "rdma")) == "tcp":
        return fail_result(
            "FN-3 流量优先级机制要求默认 RDMA 数据面，不应使用 NR_TRANSPORT=tcp",
            details=details,
        )
    if not bool(cluster.get("tcp_data_ready", False)):
        return fail_result(
            "peer 读回校验需要 TCP data channel 作为验证通道，当前 tcp_data_ready=false",
            details=details,
        )

    hi_key = _unique("fn_qos_hi")
    lo_key = _unique("fn_qos_lo")
    hi_value = "hi-priority"
    lo_value = "lo-priority"
    hi = ctx.kv_put(hi_key, hi_value, "RPC_KV_PUT_HI")
    lo = ctx.kv_put(lo_key, lo_value, "RPC_KV_PUT_LO")
    details["hi"] = hi
    details["lo"] = lo
    _require_ok(hi, "RPC_KV_PUT_HI")
    _require_ok(lo, "RPC_KV_PUT_LO")

    def qos_ok(resp: dict[str, Any], priority: str) -> bool:
        qos = resp.get("qos") or {}
        try:
            qp_idx = int(qos.get("qp_idx"))
            hi_start = int(qos.get("hi_qp_start"))
            hi_count = int(qos.get("hi_qp_count"))
            lo_start = int(qos.get("lo_qp_start"))
            lo_count = int(qos.get("lo_qp_count"))
        except (TypeError, ValueError):
            return False
        if qos.get("priority") != priority:
            return False
        if priority == "hi":
            return hi_start <= qp_idx < hi_start + hi_count
        return lo_start <= qp_idx < lo_start + lo_count

    if (
        hi.get("transport") != "rdma"
        or lo.get("transport") != "rdma"
        or bool(hi.get("degraded", True))
        or bool(lo.get("degraded", True))
        or not qos_ok(hi, "hi")
        or not qos_ok(lo, "lo")
    ):
        return fail_result(
            "高低优先级 PUT 未证明分别走 RDMA 高/低优先级 QP 分组",
            details=details,
        )

    hi_peer = ctx.rpc_json("RPC_TCP_GET_PEER", hi_key)
    lo_peer = ctx.rpc_json("RPC_TCP_GET_PEER", lo_key)
    details["hi_peer"] = hi_peer
    details["lo_peer"] = lo_peer
    if not (
        _ok(hi_peer)
        and _ok(lo_peer)
        and str(hi_peer.get("val", "")) == hi_value
        and str(lo_peer.get("val", "")) == lo_value
    ):
        return fail_result(
            "高低优先级 RDMA PUT 后 peer 读回失败",
            details=details,
        )
    hi_qos = hi.get("qos") or {}
    lo_qos = lo.get("qos") or {}
    return pass_result(
        f"QosSched 最近启动日志存在: {path}",
        f"高优先级 PUT 走 RDMA QP {hi_qos.get('qp_idx')}，低优先级 PUT 走 RDMA QP {lo_qos.get('qp_idx')}",
        "高低优先级 RDMA PUT 均完成 peer 读回同值校验",
        details=details,
    )


def rdma_fn4(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    details: dict[str, Any] = {"cluster": cluster}
    if ctx.require_peer and not bool(cluster.get("peer_alive", False)):
        return skip_result(
            "REQUIRE_PEER=1 且 peer_alive=false，不能证明跨节点 GPU Direct RDMA",
            details=details,
        )
    if str(cluster.get("transport", "rdma")) != "rdma":
        return fail_result(
            "FN-4 GPU Direct RDMA 要求数据面以 NR_TRANSPORT=rdma 启动",
            details=details,
        )

    gdr_status = ctx.rpc_json("RPC_GDR_STATUS")
    details["gdr_status_local"] = gdr_status
    if not _ok(gdr_status):
        return fail_result("RPC_GDR_STATUS 返回失败", details=details)
    if not bool(gdr_status.get("peer_gpu_enabled", False)):
        return fail_result("peer GPU MR 未启用，不能执行 GPUDirect RDMA", details=details)
    if not (
        _positive_int(gdr_status.get("peer_gpu_base"))
        and _positive_int(gdr_status.get("peer_gpu_rkey"))
        and _positive_int(gdr_status.get("peer_gpu_len"))
    ):
        return fail_result("peer GPU MR base/rkey/len 无效", details=details)

    peer_host = (
        os.environ.get("PEER_HOST")
        or os.environ.get("NR_PEER_HOST")
        or os.environ.get("PEER_SSH")
        or "xfusion4"
    )
    remote_hw = (
        "hostname; "
        "nvidia-smi --query-gpu=index,name,pci.bus_id,memory.total --format=csv,noheader; "
        "lsmod | egrep 'nvidia_peermem|nv_peer_mem'; "
        "/usr/local/cuda/bin/nvcc --version || nvcc --version || true; "
        "ibv_devinfo | head -80"
    )
    hw = ctx.run_cmd(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", peer_host, "bash", "-lc", remote_hw],
        timeout=30,
    )
    details["peer_hardware_check"] = {
        "host": peer_host,
        "returncode": hw.returncode,
        "stdout": hw.stdout,
        "stderr": hw.stderr,
    }
    hw_text = hw.stdout + "\n" + hw.stderr
    if hw.returncode != 0:
        return skip_result(f"无法通过 SSH 检查 {peer_host} GDR 硬件状态", details=details)
    if "NVIDIA" not in hw_text or (
        "nvidia_peermem" not in hw_text and "nv_peer_mem" not in hw_text
    ):
        return fail_result(
            "xfusion4 未同时证明 NVIDIA GPU 与 nvidia_peermem/nv_peer_mem 可用",
            details=details,
        )
    if "Cuda compilation tools" not in hw_text and "release 12" not in hw_text:
        return fail_result("xfusion4 未证明 CUDA 编译工具可用", details=details)
    if "hca_id:\tmlx5_0" not in hw_text and "hca_id: mlx5_0" not in hw_text:
        return fail_result("xfusion4 未证明 mlx5_0 RDMA 设备可用", details=details)

    def remote_rpc(kind: str, body: str = "", timeout: float = 20.0) -> dict[str, Any]:
        code = (
            "import socket,struct,sys;"
            "uds='/tmp/native_rdma-dp.sock';"
            f"kind={kind.encode()!r};"
            f"body={body.encode()!r};"
            "s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);"
            "s.settimeout(10);"
            "s.connect(uds);"
            "s.sendall(struct.pack('<I',len(kind))+kind+struct.pack('<I',len(body))+body);"
            "f=s.makefile('rb');"
            "h=f.read(4);"
            "n=struct.unpack('<I',h)[0];"
            "d=f.read(n);"
            "sys.stdout.buffer.write(d)"
        )
        proc = ctx.run_cmd(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", peer_host, "python3 -c " + shlex.quote(code)],
            timeout=timeout,
        )
        label = f"{peer_host}:{kind}"
        details[label] = {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        if proc.returncode != 0:
            raise FailCheck(f"远端 RPC {kind} 调用失败: {proc.stderr[-200:]}", details)
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise FailCheck(f"远端 RPC {kind} 返回非 JSON: {proc.stdout[:200]}", details) from exc

    peer_gdr_status = remote_rpc("RPC_GDR_STATUS")
    details["gdr_status_peer"] = peer_gdr_status
    if not (
        _ok(peer_gdr_status)
        and bool(peer_gdr_status.get("local_gpu_enabled", False))
        and _positive_int(peer_gdr_status.get("local_gpu_rkey"))
    ):
        return fail_result("xfusion4 本地 RPC_GDR_STATUS 未证明 GPU MR 启用", details=details)

    peer_len = int(gdr_status.get("peer_gpu_len", 0))
    bytes_n = int(os.environ.get("GDR_TEST_BYTES", "4096"))
    bytes_n = max(1, min(bytes_n, 4096, peer_len))
    offset = int(os.environ.get("GDR_TEST_OFFSET", "0"))
    seed = int(os.environ.get("GDR_TEST_SEED", "90"))
    body = f"offset={offset}&bytes={bytes_n}&seed={seed}"

    gdr_write = ctx.rpc_json("RPC_GDR_WRITE", body, timeout=20)
    details["gdr_write"] = gdr_write
    if not (
        _ok(gdr_write)
        and str(gdr_write.get("transport")) == "gpudirect_rdma"
        and not bool(gdr_write.get("degraded", True))
        and int(gdr_write.get("bytes", 0)) == bytes_n
        and _positive_int(gdr_write.get("write_ns"))
    ):
        return fail_result("RPC_GDR_WRITE 未证明 A->B GPU MR 的 RDMA WRITE 成功", details=details)

    gdr_validate = remote_rpc("RPC_GDR_VALIDATE", body)
    details["gdr_validate"] = gdr_validate
    if not (
        _ok(gdr_validate)
        and bool(gdr_validate.get("gpu_side_validate", False))
        and int(gdr_validate.get("mismatches", -1)) == 0
        and _positive_int(gdr_validate.get("validate_ns"))
    ):
        return fail_result("xfusion4 CUDA kernel 未确认 GPU buffer 内容正确", details=details)

    gdr_readback = ctx.rpc_json("RPC_GDR_READBACK", body, timeout=20)
    details["gdr_readback"] = gdr_readback
    if not (
        _ok(gdr_readback)
        and str(gdr_readback.get("transport")) == "gpudirect_rdma"
        and int(gdr_readback.get("mismatches", -1)) == 0
        and _positive_int(gdr_readback.get("read_ns"))
    ):
        return fail_result("RPC_GDR_READBACK 未证明 A 从 B GPU MR RDMA READ 读回正确", details=details)

    return pass_result(
        "xfusion4 证明 NVIDIA GPU、CUDA、nvidia_peermem/nv_peer_mem 与 mlx5_0 RDMA 设备可用",
        f"RPC_GDR_STATUS peer GPU MR 有效: base={gdr_status.get('peer_gpu_base')} len={gdr_status.get('peer_gpu_len')} rkey={gdr_status.get('peer_gpu_rkey')}",
        f"A->B RPC_GDR_WRITE 写入 GPU MR {bytes_n}B，write_ns={gdr_write.get('write_ns')}，degraded=false",
        f"xfusion4 CUDA kernel 校验 GPU buffer 通过，checksum={gdr_validate.get('checksum')} validate_ns={gdr_validate.get('validate_ns')}",
        f"A 侧 RPC_GDR_READBACK 读回校验通过，read_ns={gdr_readback.get('read_ns')} checksum={gdr_readback.get('checksum')}",
        details=details,
    )


def rdma_fn5(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    details: dict[str, Any] = {"cluster": cluster}
    if ctx.require_peer and not bool(cluster.get("peer_alive", False)):
        return skip_result(
            "REQUIRE_PEER=1 且 peer_alive=false，不能证明跨节点路由转发闭环",
            details=details,
        )
    if str(cluster.get("transport", "rdma")) == "tcp":
        return fail_result(
            "FN-5 路由负载均衡要求默认 RDMA 数据面启动，不应使用 NR_TRANSPORT=tcp",
            details=details,
        )
    if not bool(cluster.get("tcp_data_ready", False)):
        return fail_result(
            "路由转发闭环需要 TCP data channel 作为 primary 转发通道，当前 tcp_data_ready=false",
            details=details,
        )

    counts: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    local_item: dict[str, Any] | None = None
    remote_item: dict[str, Any] | None = None
    sample_n = int(os.environ.get("FN5_ROUTE_KEYS", "64"))
    if sample_n < 32:
        sample_n = 32
    for i in range(sample_n):
        key = f"{_unique('fn_route')}_{i}"
        route = ctx.rpc_json("RPC_ROUTE_QUERY", key)
        _require_ok(route, f"RPC_ROUTE_QUERY {key}")
        primary = str(route.get("primary") or "")
        if not primary:
            return fail_result("route 返回缺少 primary", details={"route": route})
        counts[primary] = counts.get(primary, 0) + 1
        items.append(route)
        if bool(route.get("local_is_primary", False)) and local_item is None:
            local_item = route
        if not bool(route.get("local_is_primary", False)) and remote_item is None:
            remote_item = route
    details.update({"counts": counts, "items": items})
    if len(counts) < 2:
        return fail_result(
            f"路由查询可用但 primary 未覆盖多个节点: {counts}",
            details=details,
        )
    if local_item is None or remote_item is None:
        return fail_result(
            "路由样本未同时覆盖本地 primary 和远端 primary",
            details=details,
        )

    local_key = str(local_item["key"])
    remote_key = str(remote_item["key"])
    local_value = "route-local-primary"
    remote_value = "route-remote-primary"
    local_put = ctx.rpc_json("RPC_ROUTE_PUT", local_key.encode() + b"\x00" + local_value.encode())
    remote_put = ctx.rpc_json("RPC_ROUTE_PUT", remote_key.encode() + b"\x00" + remote_value.encode())
    details["local_put"] = local_put
    details["remote_put"] = remote_put
    _require_ok(local_put, "RPC_ROUTE_PUT local primary")
    _require_ok(remote_put, "RPC_ROUTE_PUT remote primary")
    if bool(local_put.get("route_forwarded", True)):
        return fail_result("本地 primary route PUT 不应发生跨节点转发", details=details)
    if not bool(remote_put.get("route_forwarded", False)):
        return fail_result("远端 primary route PUT 未发生跨节点转发", details=details)
    if str(remote_put.get("forward_transport", "")) != "tcp_data_channel":
        return fail_result("远端 primary route PUT 未走 TCP data channel 转发通道", details=details)

    local_get = ctx.kv_get(local_key)
    remote_peer_get = ctx.rpc_json("RPC_TCP_GET_PEER", remote_key)
    details["local_get"] = local_get
    details["remote_peer_get"] = remote_peer_get
    if not (_ok(local_get) and str(local_get.get("val", "")) == local_value):
        return fail_result("本地 primary route PUT 后本地 GET 读回失败", details=details)
    if not (_ok(remote_peer_get) and str(remote_peer_get.get("val", "")) == remote_value):
        return fail_result("远端 primary route PUT 后 peer GET 读回失败", details=details)

    empty_replica = sum(1 for item in items if not item.get("replica"))
    details["empty_replica"] = empty_replica
    return pass_result(
        f"{sample_n} 个 key 路由查询成功，primary 分布: {counts}",
        f"本地 primary 写入未转发: key={local_key} primary={local_put.get('primary')}",
        f"远端 primary 写入已转发到 peer: key={remote_key} primary={remote_put.get('primary')} transport={remote_put.get('forward_transport')}",
        f"本地 GET 与 peer GET 均完成同值读回；replica 为空样本数={empty_replica}",
        details=details,
        )


def mempool_fn1(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    _require_peer_if_needed(ctx, cluster)
    peer_base = int(cluster.get("peer_slab_base", 0) or 0)
    peer_len = int(cluster.get("peer_slab_len", 0) or 0)
    peer_rkey = int(cluster.get("peer_slab_rkey", 0) or 0)
    peer_qps = int(cluster.get("peer_num_qp", 0) or 0)
    if peer_base <= 0 or peer_len <= 0 or peer_rkey <= 0 or peer_qps <= 0:
        return fail_result(
            "peer slab 元数据无效，不能证明远程内存区域可被 RDMA 访问",
            details={"cluster": cluster},
        )
    if cluster.get("tcp_data_ready") is not True:
        return fail_result(
            "TCP data channel 未就绪，无法从 peer 读回校验 RDMA 写入结果",
            details={"cluster": cluster},
        )
    key = _unique("fn_zero_copy")
    value = "rdma-zero-copy-probe"
    put = ctx.kv_put(key, value, kind="RPC_KV_PUT_RDMA")
    _require_ok(put, "RPC_KV_PUT_RDMA")
    transport = str(put.get("transport", ""))
    degraded = bool(put.get("degraded", False))
    offset = int(put.get("offset", -1) or -1)
    size = int(put.get("size", 0) or 0)
    repl_ns = int(put.get("repl_ns", 0) or 0)
    if transport != "rdma" or degraded or repl_ns <= 0:
        return fail_result(
            "PUT 未走同步 RDMA 复制路径，或返回 degraded/无复制时延",
            details={"cluster": cluster, "put": put},
        )
    if offset < 0 or size != len(value) or offset + size > peer_len:
        return fail_result(
            "PUT 返回的远端 slab offset/size 超出 peer slab 有效范围",
            details={
                "cluster": cluster,
                "put": put,
                "peer_slab_range": {"base": peer_base, "len": peer_len},
            },
        )

    peer_get: dict[str, Any] = {}
    deadline = time.time() + float(os.environ.get("FN1_PEER_READBACK_TIMEOUT", "3"))
    while True:
        peer_get = ctx.rpc_json("RPC_TCP_GET_PEER", key)
        if peer_get.get("ok") is True and str(peer_get.get("val", "")) == value:
            break
        if time.time() >= deadline:
            return fail_result(
                "RDMA PUT 后未能从 peer 读回同一 value",
                details={"cluster": cluster, "put": put, "peer_get": peer_get},
            )
        time.sleep(0.1)

    return pass_result(
        f"RPC_KV_PUT_RDMA 走 RDMA: transport={transport} degraded={degraded} repl_ns={repl_ns}",
        f"远端 slab 元数据有效: base={peer_base} len={peer_len} rkey={peer_rkey} qps={peer_qps}",
        f"offset/size 在 peer slab 范围内: offset={offset} size={size}",
        f"RPC_TCP_GET_PEER 从 peer 读回同一 value: key={key}",
        details={"cluster": cluster, "put": put, "peer_get": peer_get},
    )


def mempool_fn2(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    _require_peer_if_needed(ctx, cluster)
    local_len = int(cluster.get("local_slab_len", 0) or 0)
    peer_len = int(cluster.get("peer_slab_len", 0) or 0)
    if (
        int(cluster.get("local_slab_base", 0) or 0) <= 0
        or local_len <= 0
        or int(cluster.get("local_slab_lkey", 0) or 0) <= 0
        or int(cluster.get("local_slab_rkey", 0) or 0) <= 0
        or int(cluster.get("peer_slab_base", 0) or 0) <= 0
        or peer_len <= 0
        or int(cluster.get("peer_slab_rkey", 0) or 0) <= 0
        or int(cluster.get("peer_num_qp", 0) or 0) <= 0
    ):
        return fail_result(
            "本地或 peer slab/MR 元数据无效，不能证明分布式内存池 API 绑定真实数据面资源",
            details={"cluster": cluster},
        )
    if cluster.get("tcp_data_ready") is not True:
        return fail_result(
            "TCP data channel 未就绪，无法从 peer 读回校验分布式 PUT 结果",
            details={"cluster": cluster},
        )

    key = _unique("fn_pool_api")
    value = "distributed-pool-api-value"
    put = ctx.kv_put(key, value)
    _require_ok(put, "RPC_KV_PUT")
    transport = str(put.get("transport", ""))
    degraded = bool(put.get("degraded", False))
    offset = int(put.get("offset", -1) or -1)
    size = int(put.get("size", 0) or 0)
    if transport != "rdma" or degraded:
        return fail_result(
            "封装 API 未走 RDMA 分布式写入路径，或处于 degraded 本地写入",
            details={"cluster": cluster, "put": put},
        )
    if offset < 0 or size != len(value) or offset + size > local_len or offset + size > peer_len:
        return fail_result(
            "PUT 返回的 offset/size 不在本地或 peer slab 有效范围内",
            details={
                "cluster": cluster,
                "put": put,
                "local_slab_len": local_len,
                "peer_slab_len": peer_len,
            },
        )

    got = ctx.kv_get(key)
    _require_ok(got, "RPC_KV_GET")
    peer_get = ctx.rpc_json("RPC_TCP_GET_PEER", key)
    _require_ok(peer_get, "RPC_TCP_GET_PEER")
    if str(got.get("val", "")) == value and str(peer_get.get("val", "")) == value:
        return pass_result(
            f"UDS 封装 API 闭环成功: RPC_KV_PUT -> RPC_KV_GET key={key} hit={got.get('hit')} size={got.get('size')}",
            f"RPC_KV_PUT 屏蔽底层 RDMA 细节但返回 transport={transport} degraded={degraded} offset={offset}",
            "本地与 peer slab/MR 元数据有效，offset/size 同时落在两端 slab 范围内",
            "RPC_TCP_GET_PEER 从 peer 读回同一 value，证明分布式内存池 API 的远端副本可见",
            details={"cluster": cluster, "put": put, "get": got, "peer_get": peer_get},
        )
    return fail_result(
        "本地 GET 或 peer GET 内容与 PUT 不一致",
        details={"cluster": cluster, "put": put, "get": got, "peer_get": peer_get, "expected": value},
    )


def mempool_fn3(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    _require_peer_if_needed(ctx, cluster)
    local_base = int(cluster.get("local_slab_base", 0) or 0)
    local_len = int(cluster.get("local_slab_len", 0) or 0)
    local_lkey = int(cluster.get("local_slab_lkey", 0) or 0)
    local_rkey = int(cluster.get("local_slab_rkey", 0) or 0)
    peer_base = int(cluster.get("peer_slab_base", 0) or 0)
    peer_len = int(cluster.get("peer_slab_len", 0) or 0)
    peer_rkey = int(cluster.get("peer_slab_rkey", 0) or 0)
    peer_qps = int(cluster.get("peer_num_qp", 0) or 0)
    fields_ok = all(
        value > 0
        for value in (local_base, local_len, local_lkey, local_rkey, peer_base, peer_len, peer_rkey, peer_qps)
    )
    if not fields_ok:
        return fail_result(
            "本地或 peer slab 命名元数据无效",
            details={"cluster": cluster},
        )

    pools = ctx.rpc_json("RPC_MEMPOOL_POOLS")
    _require_ok(pools, "RPC_MEMPOOL_POOLS")
    local = pools.get("local") or {}
    remote = pools.get("remote") or {}
    local_name = str(local.get("name", ""))
    remote_name = str(remote.get("name", ""))
    local_registry_ok = (
        local.get("ok") is True
        and local_name == "default/slab1k"
        and int(local.get("base", 0) or 0) == local_base
        and int(local.get("len", 0) or 0) == local_len
        and int(local.get("lkey", 0) or 0) == local_lkey
        and int(local.get("rkey", 0) or 0) == local_rkey
        and int(local.get("pool_id", 0) or 0) > 0
    )
    remote_registry_ok = (
        remote.get("ok") is True
        and remote_name == local_name
        and int(remote.get("base", 0) or 0) == peer_base
        and int(remote.get("len", 0) or 0) == peer_len
        and int(remote.get("rkey", 0) or 0) == peer_rkey
    )
    if local_registry_ok and remote_registry_ok:
        return pass_result(
            f"统一 pool 名称有效: local={local_name} remote={remote_name} peer_id={pools.get('peer_id')}",
            f"本地 registry 与 cluster slab 元数据一致: base={local_base} len={local_len} lkey={local_lkey} rkey={local_rkey}",
            f"远端 registry 与 OOB peer slab 元数据一致: base={peer_base} len={peer_len} rkey={peer_rkey} qps={peer_qps}",
            details={"cluster": cluster, "pools": pools},
        )
    return fail_result(
        "PoolRegistry 本地/远端同名 pool 与 OOB/cluster 元数据不一致",
        details={
            "cluster": cluster,
            "pools": pools,
            "local_registry_ok": local_registry_ok,
            "remote_registry_ok": remote_registry_ok,
        },
    )


def mempool_fn4(ctx: FnContext) -> CheckResult:
    cluster = ctx.cluster_status()
    _require_ok(cluster, "RPC_CLUSTER_STATUS")
    _require_peer_if_needed(ctx, cluster)
    peer_base = int(cluster.get("peer_slab_base", 0) or 0)
    peer_len = int(cluster.get("peer_slab_len", 0) or 0)
    peer_rkey = int(cluster.get("peer_slab_rkey", 0) or 0)
    peer_qps = int(cluster.get("peer_num_qp", 0) or 0)
    transport = str(cluster.get("transport", ""))
    tcp_ready = bool(cluster.get("tcp_data_ready", False))
    if not all(v > 0 for v in (peer_base, peer_len, peer_rkey, peer_qps)):
        return fail_result("peer slab/RDMA 元数据无效，不能验证跨节点远端内存放置", details={"cluster": cluster})
    if transport != "rdma":
        return fail_result("FN-4 要求 RDMA 数据面，当前 transport 不是 rdma", details={"cluster": cluster})
    if not tcp_ready:
        return fail_result("tcp_data_ready=false，无法从 peer 读回校验远端放置内容", details={"cluster": cluster})

    before = ctx.rpc_json("RPC_MEMPOOL_ADAPT_STATS")
    _require_ok(before, "RPC_MEMPOOL_ADAPT_STATS before")
    key = _unique("fn_adapt_hot")
    value = "adaptive-remote-to-local-payload"
    put = ctx.rpc_json("RPC_MEMPOOL_ADAPT_PUT", key.encode() + b"\x00" + value.encode())
    _require_ok(put, "RPC_MEMPOOL_ADAPT_PUT")
    remote_offset = int(put.get("remote_offset", -1) or -1)
    size = int(put.get("size", 0) or 0)
    if (
        put.get("transport") != "rdma"
        or put.get("placement") != "remote"
        or put.get("degraded") is not False
        or put.get("local_cached") is not False
        or remote_offset < 0
        or size != len(value)
        or remote_offset + size > peer_len
    ):
        return fail_result(
            "自适应 PUT 未证明冷对象先放置到远端 RDMA slab",
            details={"cluster": cluster, "before": before, "put": put, "expected_size": len(value)},
        )

    peer_get = None
    for _ in range(10):
        candidate = ctx.rpc_json("RPC_TCP_GET_PEER", key)
        if candidate.get("ok") is True and str(candidate.get("val", "")) == value:
            peer_get = candidate
            break
        peer_get = candidate
        time.sleep(0.05)
    if not (peer_get and peer_get.get("ok") is True and str(peer_get.get("val", "")) == value):
        return fail_result(
            "远端 slab 放置后 peer 端无法读回同一对象",
            details={"cluster": cluster, "put": put, "peer_get": peer_get},
        )

    hot_threshold = int(put.get("hot_threshold", 3) or 3)
    adaptive_gets: list[dict[str, Any]] = []
    first_get = ctx.rpc_json("RPC_MEMPOOL_ADAPT_GET", key)
    _require_ok(first_get, "RPC_MEMPOOL_ADAPT_GET first")
    adaptive_gets.append(first_get)
    if (
        first_get.get("hit") != "remote_rdma_read"
        or first_get.get("placement_after") != "remote"
        or first_get.get("migrated") is not False
        or str(first_get.get("val", "")) != value
    ):
        return fail_result(
            "首次访问没有保持远端放置并通过 RDMA READ 读取",
            details={"cluster": cluster, "put": put, "first_get": first_get},
        )

    migrated_get = None
    for _ in range(max(1, hot_threshold)):
        got = ctx.rpc_json("RPC_MEMPOOL_ADAPT_GET", key)
        _require_ok(got, "RPC_MEMPOOL_ADAPT_GET hot")
        adaptive_gets.append(got)
        if got.get("migrated") is True or got.get("hit") == "remote_to_local_migrate":
            migrated_get = got
            break
    if not migrated_get:
        return fail_result(
            f"连续访问达到热点阈值 {hot_threshold} 后未触发远端到本地迁移",
            details={"cluster": cluster, "put": put, "adaptive_gets": adaptive_gets},
        )
    local_offset = int(migrated_get.get("local_offset", -1) or -1)
    if (
        migrated_get.get("placement_before") != "remote"
        or migrated_get.get("placement_after") != "local"
        or migrated_get.get("transport") != "rdma"
        or local_offset < 0
        or str(migrated_get.get("val", "")) != value
    ):
        return fail_result(
            "热点迁移响应未证明 RDMA READ 后落到本地 slab",
            details={"cluster": cluster, "put": put, "adaptive_gets": adaptive_gets, "migrated_get": migrated_get},
        )

    local_get = ctx.kv_get(key)
    _require_ok(local_get, "RPC_KV_GET after adaptive migrate")
    if str(local_get.get("hit", "")) != "local" or str(local_get.get("val", "")) != value:
        return fail_result(
            "热点迁移后普通 RPC_KV_GET 未从本地 DRAM 命中",
            details={
                "cluster": cluster,
                "put": put,
                "adaptive_gets": adaptive_gets,
                "migrated_get": migrated_get,
                "local_get": local_get,
            },
        )

    after = ctx.rpc_json("RPC_MEMPOOL_ADAPT_STATS")
    _require_ok(after, "RPC_MEMPOOL_ADAPT_STATS after")
    before_migrations = int(before.get("migrations", 0) or 0)
    after_migrations = int(after.get("migrations", 0) or 0)
    if after_migrations <= before_migrations:
        return fail_result(
            "自适应迁移统计未增加",
            details={"before": before, "after": after, "put": put, "adaptive_gets": adaptive_gets},
        )

    if (
        put.get("placement") == "remote"
        and peer_get.get("ok") is True
        and first_get.get("hit") == "remote_rdma_read"
        and migrated_get.get("hit") == "remote_to_local_migrate"
        and local_get.get("hit") == "local"
    ):
        return pass_result(
            f"冷对象自适应放置到远端 RDMA slab: remote_offset={remote_offset} size={size}",
            f"首次访问保持远端放置并通过 RDMA READ 读取: hit={first_get.get('hit')} access_count={first_get.get('access_count')}",
            f"热点阈值 {hot_threshold} 次访问后迁回本地 slab: local_offset={local_offset} rdma_read_ns={migrated_get.get('rdma_read_ns')}",
            f"迁移后普通 RPC_KV_GET 本地命中: hit={local_get.get('hit')}",
            details={
                "cluster": cluster,
                "before": before,
                "put": put,
                "peer_get": peer_get,
                "adaptive_gets": adaptive_gets,
                "migrated_get": migrated_get,
                "local_get": local_get,
                "after": after,
            },
        )
    return fail_result(
        "跨节点远端放置和热点本地化迁移闭环不成立",
        details={
            "cluster": cluster,
            "before": before,
            "put": put,
            "peer_get": peer_get,
            "adaptive_gets": adaptive_gets,
            "migrated_get": migrated_get,
            "local_get": local_get,
            "after": after,
        },
    )


def mempool_fn5(ctx: FnContext) -> CheckResult:
    base_tenant = 1000 + (int(time.time()) % 100000)
    tenant_a = base_tenant
    tenant_b = base_tenant + 100000
    pool = "default/slab1k"
    key = _unique("fn_iso_shared")
    value_a = "tenant-a-private-value"
    value_b = "tenant-b-private-value"

    deny_a0 = ctx.rpc_json("RPC_ISO_DENY", f"{tenant_a} {pool}")
    deny_b0 = ctx.rpc_json("RPC_ISO_DENY", f"{tenant_b} {pool}")
    _require_ok(deny_a0, "RPC_ISO_DENY tenant_a initial")
    _require_ok(deny_b0, "RPC_ISO_DENY tenant_b initial")
    denied_a_before = ctx.kv_put_tenant(tenant_a, key, "denied-before-allow")
    denied_b_before = ctx.kv_put_tenant(tenant_b, key, "denied-before-allow")

    allow_a = ctx.rpc_json("RPC_ISO_ALLOW", f"{tenant_a} {pool}")
    _require_ok(allow_a, "RPC_ISO_ALLOW tenant_a")
    list_after_allow_a = ctx.rpc_json("RPC_ISO_LIST")
    _require_ok(list_after_allow_a, "RPC_ISO_LIST after allow tenant_a")
    allowed_a = ctx.kv_put_tenant(tenant_a, key, value_a)
    get_a = ctx.kv_get(key, tenant_a)
    get_b_before_allow = ctx.kv_get(key, tenant_b)

    allow_b = ctx.rpc_json("RPC_ISO_ALLOW", f"{tenant_b} {pool}")
    _require_ok(allow_b, "RPC_ISO_ALLOW tenant_b")
    get_b_before_put = ctx.kv_get(key, tenant_b)
    allowed_b = ctx.kv_put_tenant(tenant_b, key, value_b)
    get_b = ctx.kv_get(key, tenant_b)
    get_a_after_b = ctx.kv_get(key, tenant_a)

    deny_a = ctx.rpc_json("RPC_ISO_DENY", f"{tenant_a} {pool}")
    _require_ok(deny_a, "RPC_ISO_DENY tenant_a final")
    denied_a_get = ctx.kv_get(key, tenant_a)
    denied_a_after = ctx.kv_put_tenant(tenant_a, key + "_after", "denied-after-revoke")
    get_b_after_deny_a = ctx.kv_get(key, tenant_b)

    deny_b = ctx.rpc_json("RPC_ISO_DENY", f"{tenant_b} {pool}")
    _require_ok(deny_b, "RPC_ISO_DENY tenant_b final")
    denied_b_after = ctx.kv_put_tenant(tenant_b, key + "_after", "denied-after-revoke")
    list_after_deny = ctx.rpc_json("RPC_ISO_LIST")
    _require_ok(list_after_deny, "RPC_ISO_LIST after deny")

    allowed_after_a = set(str(item) for item in (list_after_allow_a.get("allowed") or []))
    allowed_after_deny = set(str(item) for item in (list_after_deny.get("allowed") or []))
    tenant_a_acl = f"{tenant_a}|{pool}"
    tenant_b_acl = f"{tenant_b}|{pool}"
    if (
        denied_a_before.get("ok") is False
        and denied_b_before.get("ok") is False
        and tenant_a_acl in allowed_after_a
        and allowed_a.get("ok") is True
        and get_a.get("ok") is True
        and str(get_a.get("val", "")) == value_a
        and get_b_before_allow.get("ok") is False
        and get_b_before_put.get("ok") is False
        and "not found" in str(get_b_before_put.get("err", ""))
        and allowed_b.get("ok") is True
        and get_b.get("ok") is True
        and str(get_b.get("val", "")) == value_b
        and get_a_after_b.get("ok") is True
        and str(get_a_after_b.get("val", "")) == value_a
        and denied_a_get.get("ok") is False
        and denied_a_after.get("ok") is False
        and get_b_after_deny_a.get("ok") is True
        and str(get_b_after_deny_a.get("val", "")) == value_b
        and denied_b_after.get("ok") is False
        and tenant_a_acl not in allowed_after_deny
        and tenant_b_acl not in allowed_after_deny
    ):
        return pass_result(
            f"tenant={tenant_a} 完成拒绝->允许->读取->撤销->拒绝闭环",
            f"tenant={tenant_a} 与 tenant={tenant_b} 使用同一逻辑 key 时读回各自 value，证明命名空间隔离",
            f"RPC_ISO_LIST 证明 ACL 授权/撤销状态生效: {tenant_a_acl} allow 后存在，最终撤销后不存在",
            details={
                "tenant_a": tenant_a,
                "tenant_b": tenant_b,
                "pool": pool,
                "key": key,
                "deny_a0": deny_a0,
                "deny_b0": deny_b0,
                "denied_a_before": denied_a_before,
                "denied_b_before": denied_b_before,
                "allow_a": allow_a,
                "list_after_allow_a": list_after_allow_a,
                "allowed_a": allowed_a,
                "get_a": get_a,
                "get_b_before_allow": get_b_before_allow,
                "allow_b": allow_b,
                "get_b_before_put": get_b_before_put,
                "allowed_b": allowed_b,
                "get_b": get_b,
                "get_a_after_b": get_a_after_b,
                "deny_a": deny_a,
                "denied_a_get": denied_a_get,
                "denied_a_after": denied_a_after,
                "get_b_after_deny_a": get_b_after_deny_a,
                "deny_b": deny_b,
                "denied_b_after": denied_b_after,
                "list_after_deny": list_after_deny,
            },
        )
    return fail_result(
        "租户隔离拒/允/拒闭环或双租户命名空间隔离不成立",
        details={
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "pool": pool,
            "key": key,
            "deny_a0": deny_a0,
            "deny_b0": deny_b0,
            "denied_a_before": denied_a_before,
            "denied_b_before": denied_b_before,
            "allow_a": allow_a,
            "list_after_allow_a": list_after_allow_a,
            "allowed_a": allowed_a,
            "get_a": get_a,
            "get_b_before_allow": get_b_before_allow,
            "allow_b": allow_b,
            "get_b_before_put": get_b_before_put,
            "allowed_b": allowed_b,
            "get_b": get_b,
            "get_a_after_b": get_a_after_b,
            "deny_a": deny_a,
            "denied_a_get": denied_a_get,
            "denied_a_after": denied_a_after,
            "get_b_after_deny_a": get_b_after_deny_a,
            "deny_b": deny_b,
            "denied_b_after": denied_b_after,
            "list_after_deny": list_after_deny,
        },
    )


def _cmd_details(proc: Any | None) -> dict[str, Any] | None:
    if proc is None:
        return None
    return {
        "rc": proc.returncode,
        "stdout_tail": str(proc.stdout or "")[-1000:],
        "stderr_tail": str(proc.stderr or "")[-1000:],
    }


def _wait_cluster_status(
    ctx: FnContext,
    label: str,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout_s: float,
    interval_s: float = 0.5,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {"ok": False, "err": f"{label} not sampled"}
    while time.time() < deadline:
        try:
            last = ctx.cluster_status()
            if _ok(last) and predicate(last):
                return last
        except Exception as exc:  # UDS may disappear briefly during recovery.
            last = {"ok": False, "err": repr(exc)}
            ctx.log(f"{label} poll failed: {exc!r}")
        time.sleep(interval_s)
    return last


def _wait_peer_get(
    ctx: FnContext,
    key: str,
    expected: str,
    *,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {"ok": False, "err": "not sampled"}
    while time.time() < deadline:
        try:
            last = ctx.rpc_json("RPC_TCP_GET_PEER", key, timeout=2.0)
            if last.get("ok") is True and str(last.get("val", "")) == expected:
                return last
        except Exception as exc:
            last = {"ok": False, "err": repr(exc)}
            ctx.log(f"peer get poll failed: {exc!r}")
        time.sleep(0.2)
    return last


def _ha_active_drill(ctx: FnContext, cluster: dict[str, Any]) -> CheckResult | None:
    peer_ssh = os.environ.get("PEER_SSH") or os.environ.get("NR_PEER_SSH")
    peer_dp_path = os.environ.get("PEER_DP_PATH") or os.environ.get("NR_PEER_DP_PATH")
    peer_start_cmd = os.environ.get("PEER_START_CMD") or os.environ.get("NR_PEER_START_CMD")
    recovery_cmd = (
        os.environ.get("FN6_RECOVERY_CMD")
        or os.environ.get("NR_HA_RECOVERY_CMD")
        or os.environ.get("HA_RECOVERY_CMD")
    )
    if not ctx.allow_destructive:
        return None
    if not peer_ssh or not peer_dp_path:
        raise SkipCheck("ALLOW_DESTRUCTIVE=1 但未提供 PEER_SSH/PEER_DP_PATH")
    if not recovery_cmd and not peer_start_cmd:
        raise SkipCheck(
            "ALLOW_DESTRUCTIVE=1 但未提供 FN6_RECOVERY_CMD 或 PEER_START_CMD，"
            "为避免演练后 peer 长时间离线，跳过主动故障演练"
        )
    _require_peer_if_needed(ctx, cluster)
    if str(cluster.get("transport", "")) != "rdma":
        return fail_result(
            "主动高可靠演练要求 NR_TRANSPORT=rdma，避免 TCP fallback 冒充 RDMA peer 故障降级",
            details={"cluster": cluster},
        )
    before = int(cluster.get("degraded_puts", 0) or 0)
    before_bytes = int(cluster.get("degraded_bytes", 0) or 0)
    kill_cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=3",
        "-o", "StrictHostKeyChecking=no",
        peer_ssh,
        f"pkill -9 -f {shlex.quote(peer_dp_path)}",
    ]
    details: dict[str, Any] = {
        "before": cluster,
        "peer_ssh": peer_ssh,
        "peer_dp_path": peer_dp_path,
        "recovery_cmd": recovery_cmd,
        "peer_start_cmd": peer_start_cmd,
    }
    restore = None
    recovery = None
    recovery_status: dict[str, Any] = {}
    post_put: dict[str, Any] = {}
    post_peer_get: dict[str, Any] = {}
    drill_error = ""
    kill = ctx.run_cmd(kill_cmd, timeout=8.0)
    details["kill"] = _cmd_details(kill)
    try:
        if kill.returncode != 0:
            drill_error = f"kill peer 命令失败 rc={kill.returncode}"
            return fail_result(drill_error, details=details)

        down_timeout = float(os.environ.get("FN6_PEER_DOWN_TIMEOUT", "10"))
        mid = _wait_cluster_status(
            ctx,
            "wait peer down",
            lambda s: s.get("peer_alive") is False,
            timeout_s=down_timeout,
        )
        details["mid"] = mid

        key = _unique("fn_ha_degraded")
        value = "during-outage-local-available"
        put = ctx.kv_put(key, value)
        got = ctx.kv_get(key)
        after_status = ctx.cluster_status()
        after = int(after_status.get("degraded_puts", 0) or 0)
        after_bytes = int(after_status.get("degraded_bytes", 0) or 0)
        try:
            peer_get_during = ctx.rpc_json("RPC_TCP_GET_PEER", key, timeout=1.0)
        except Exception as exc:
            peer_get_during = {"ok": False, "err": repr(exc)}
        details.update({
            "key": key,
            "value": value,
            "put_during_outage": put,
            "get_during_outage": got,
            "peer_get_during_outage": peer_get_during,
            "after": after_status,
        })

        degraded_ok = (
            mid.get("peer_alive") is False
            and put.get("ok") is True
            and put.get("degraded") is True
            and str(put.get("transport", "")) == "rdma"
            and got.get("ok") is True
            and str(got.get("val", "")) == value
            and after > before
            and after_bytes >= before_bytes + len(value)
        )
        if not degraded_ok:
            drill_error = "主动故障演练未观测到预期本地可用降级写入"
            return fail_result(drill_error, details=details)

        if recovery_cmd:
            recovery_timeout = float(os.environ.get("FN6_RECOVERY_CMD_TIMEOUT", "240"))
            recovery = ctx.run_cmd(["bash", "-lc", recovery_cmd], timeout=recovery_timeout)
            details["recovery"] = _cmd_details(recovery)
            if recovery.returncode != 0:
                drill_error = f"恢复命令失败 rc={recovery.returncode}"
                return fail_result(drill_error, details=details)

            recovery_wait = float(os.environ.get("FN6_RECOVERY_WAIT_TIMEOUT", "30"))
            recovery_status = _wait_cluster_status(
                ctx,
                "wait peer recovery",
                lambda s: s.get("peer_alive") is True and s.get("tcp_data_ready") is True,
                timeout_s=recovery_wait,
            )
            details["recovery_status"] = recovery_status
            post_key = _unique("fn_ha_recovered")
            post_value = "after-recovery-rdma-replicated"
            if recovery_status.get("peer_alive") is True:
                post_put = ctx.kv_put(post_key, post_value)
                post_peer_get = _wait_peer_get(
                    ctx,
                    post_key,
                    post_value,
                    timeout_s=float(os.environ.get("FN6_POST_RECOVERY_READBACK_TIMEOUT", "5")),
                )
            details["post_recovery"] = {
                "key": post_key,
                "value": post_value,
                "put": post_put,
                "peer_get": post_peer_get,
            }
            recovered_ok = (
                recovery_status.get("peer_alive") is True
                and recovery_status.get("tcp_data_ready") is True
                and post_put.get("ok") is True
                and str(post_put.get("transport", "")) == "rdma"
                and post_put.get("degraded") is False
                and post_peer_get.get("ok") is True
                and str(post_peer_get.get("val", "")) == post_value
            )
            if not recovered_ok:
                drill_error = "恢复后未观测到 RDMA 非降级复制和 peer 读回"
                return fail_result(drill_error, details=details)

            return pass_result(
                f"主动故障演练成功: peer_alive true->false, degraded_puts {before}->{after}",
                f"故障期间 RPC_KV_PUT 返回 degraded=true 且本地 RPC_KV_GET 读回: key={key}",
                "恢复命令执行后 peer_alive=true，后续 PUT 重新走 RDMA 非降级复制并可从 peer 读回",
                details=details,
            )

        # Compatibility path for older manual drills: prove outage availability
        # and run the provided peer-start command for cleanup, but do not claim
        # full recovery because a restarted RDMA process needs a fresh OOB/QP
        # handshake with the local node.
        restore_cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            peer_ssh,
            peer_start_cmd or "",
        ]
        restore = ctx.run_cmd(restore_cmd, timeout=float(os.environ.get("FN6_PEER_START_TIMEOUT", "30")))
        details["restore"] = _cmd_details(restore)
        return pass_result(
            f"主动故障演练成功: peer_alive true->false, degraded_puts {before}->{after}",
            f"故障期间 RPC_KV_PUT 返回 degraded=true 且本地 RPC_KV_GET 读回: key={key}",
            "仅提供 PEER_START_CMD，已做 peer 启动清理；未证明恢复后重新 RDMA 复制",
            details=details,
            completion="基本完整",
        )
    except Exception as exc:
        drill_error = f"主动故障演练异常: {exc!r}"
        details["exception"] = repr(exc)
        return fail_result(drill_error, details=details)
    finally:
        if drill_error and recovery_cmd and recovery is None:
            try:
                cleanup = ctx.run_cmd(
                    ["bash", "-lc", recovery_cmd],
                    timeout=float(os.environ.get("FN6_RECOVERY_CMD_TIMEOUT", "240")),
                )
                details["cleanup_recovery"] = _cmd_details(cleanup)
            except Exception as exc:
                details["cleanup_recovery_error"] = repr(exc)
    return fail_result(
        "主动故障演练未观测到预期降级写入",
        details=details,
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
            "默认未执行主动 kill peer；完整演练需 ALLOW_DESTRUCTIVE=1、PEER_SSH/PEER_DP_PATH 和 FN6_RECOVERY_CMD",
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
