from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .catalog import get_spec


EXIT_CODES = {
    "PASS": 0,
    "FAIL": 1,
    "SKIP": 2,
    "WAIVED": 0,
}


COMPLETION_BY_STATUS = {
    "PASS": "完成",
    "FAIL": "未完成",
    "SKIP": "未完成",
    "WAIVED": "硬件/环境豁免",
}


class CheckExit(Exception):
    def __init__(
        self,
        status: str,
        evidence: str,
        *,
        completion: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(evidence)
        self.status = status
        self.evidence = evidence
        self.completion = completion
        self.details = details or {}


class SkipCheck(CheckExit):
    def __init__(self, evidence: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("SKIP", evidence, details=details)


class FailCheck(CheckExit):
    def __init__(self, evidence: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("FAIL", evidence, details=details)


@dataclass
class CheckResult:
    status: str
    evidence: list[str]
    details: dict[str, Any]
    completion: str | None = None


def pass_result(*evidence: str, details: dict[str, Any] | None = None,
                completion: str | None = None) -> CheckResult:
    return CheckResult("PASS", [x for x in evidence if x], details or {}, completion)


def fail_result(*evidence: str, details: dict[str, Any] | None = None,
                completion: str | None = None) -> CheckResult:
    return CheckResult("FAIL", [x for x in evidence if x], details or {}, completion)


def skip_result(*evidence: str, details: dict[str, Any] | None = None) -> CheckResult:
    return CheckResult("SKIP", [x for x in evidence if x], details or {}, None)


def waived_result(*evidence: str, details: dict[str, Any] | None = None) -> CheckResult:
    return CheckResult("WAIVED", [x for x in evidence if x], details or {}, "硬件/环境豁免")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _now_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


class FnContext:
    def __init__(self, spec: dict[str, Any], fn_dir: Path) -> None:
        self.spec = spec
        self.fn_dir = fn_dir.resolve()
        self.module = str(spec["module"])
        self.fn_id = str(spec["fn_id"])
        self.functions_dir = self.fn_dir.parents[1]
        self.repo_root = Path(os.environ.get("REPO_ROOT", self.fn_dir.parents[2])).resolve()
        self.native_root = self.repo_root / "native_rdma"
        self.out_dir = Path(os.environ.get("OUT_DIR", self.fn_dir)).resolve()
        self.log_dir = Path(os.environ.get("LOG_DIR", self.out_dir / "logs")).resolve()
        self.uds = os.environ.get("UDS", "/tmp/native_rdma-dp.sock")
        self.ctrl_url = os.environ.get("CTRL_URL", "http://127.0.0.1:5000").rstrip("/")
        self.require_peer = os.environ.get("REQUIRE_PEER", "1") not in {"0", "false", "False"}
        self.allow_destructive = os.environ.get("ALLOW_DESTRUCTIVE", "0") in {"1", "true", "True"}
        self.current_node = os.environ.get("CURRENT_NODE") or os.environ.get("NR_ROLE") or ""
        self.run_ts = os.environ.get("RUN_TS", _now_stamp())
        self.started_at = _now_iso()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.run_log = self.log_dir / f"run_{self.run_ts}.log"
        self.run_json = self.log_dir / f"run_{self.run_ts}.json"
        self.raw_json = self.out_dir / "raw.json"
        self.summary_md = self.out_dir / "summary.md"
        self._log_lines: list[str] = []
        self._raw_calls: list[dict[str, Any]] = []
        self.log(f"start {self.module}/{self.fn_id} {spec['name']}")
        self.log(f"repo_root={self.repo_root}")
        self.log(f"uds={self.uds} ctrl_url={self.ctrl_url}")

    def log(self, message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        self._log_lines.append(line)

    def is_socket(self) -> bool:
        return Path(self.uds).is_socket()

    def require_uds(self) -> None:
        if not self.is_socket():
            raise SkipCheck(f"UDS socket 不存在或不可用: {self.uds}")

    def rpc_raw(self, kind: str, body: bytes | str = b"", timeout: float = 3.0) -> bytes:
        self.require_uds()
        if isinstance(body, str):
            body_b = body.encode()
        else:
            body_b = body
        self.log(f"rpc {kind} body_len={len(body_b)}")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect(self.uds)
            k = kind.encode()
            sock.sendall(struct.pack("<I", len(k)) + k + struct.pack("<I", len(body_b)) + body_b)
            hdr = self._recv_exact(sock, 4)
            size = struct.unpack("<I", hdr)[0]
            data = self._recv_exact(sock, size)
            preview = data[:500].decode("utf-8", errors="replace")
            self.log(f"rpc {kind} resp_len={len(data)} resp={preview}")
            self._raw_calls.append({
                "kind": kind,
                "body_len": len(body_b),
                "response_len": len(data),
                "response_preview": preview,
            })
            return data
        except (OSError, socket.timeout) as exc:
            raise SkipCheck(f"UDS RPC {kind} 调用失败: {exc}") from exc
        finally:
            sock.close()

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> bytes:
        out = b""
        while len(out) < n:
            chunk = sock.recv(n - len(out))
            if not chunk:
                raise ConnectionError(f"short read: expected {n}, got {len(out)}")
            out += chunk
        return out

    def rpc_json(self, kind: str, body: bytes | str = b"", timeout: float = 3.0) -> dict[str, Any]:
        raw = self.rpc_raw(kind, body, timeout)
        text = raw.decode("utf-8", errors="replace")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FailCheck(f"RPC {kind} 返回非 JSON: {text[:200]}") from exc
        return data

    def http_json(self, method: str, path: str, body: dict[str, Any] | None = None,
                  timeout: float = 3.0) -> dict[str, Any]:
        url = self.ctrl_url + path
        payload = None
        headers = {"Accept": "application/json"}
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=payload, method=method, headers=headers)
        self.log(f"http {method} {url}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SkipCheck(f"HTTP {url} 不可达: {exc}") from exc
        self.log(f"http {path} resp={data[:500]}")
        try:
            return json.loads(data)
        except json.JSONDecodeError as exc:
            raise FailCheck(f"HTTP {path} 返回非 JSON: {data[:200]}") from exc

    def kv_put(self, key: str, value: str | bytes, kind: str = "RPC_KV_PUT") -> dict[str, Any]:
        val = value.encode() if isinstance(value, str) else value
        body = key.encode() + b"\x00" + val
        return self.rpc_json(kind, body)

    def kv_put_tenant(self, tenant_id: int, key: str, value: str | bytes) -> dict[str, Any]:
        val = value.encode() if isinstance(value, str) else value
        body = f"T{tenant_id}:{key}".encode() + b"\x00" + val
        return self.rpc_json("RPC_KV_PUT", body)

    def kv_get(self, key: str, tenant_id: int | None = None) -> dict[str, Any]:
        if tenant_id is None:
            body = key.encode()
        else:
            body = f"T{tenant_id}:{key}".encode()
        return self.rpc_json("RPC_KV_GET", body)

    def batch_put(self, items: list[tuple[str, bytes | str]]) -> dict[str, Any]:
        body = struct.pack("<I", len(items))
        for key, value in items:
            val = value.encode() if isinstance(value, str) else value
            key_b = key.encode()
            body += struct.pack("<H", len(key_b)) + key_b
            body += struct.pack("<I", len(val)) + val
        return self.rpc_json("RPC_KV_PUT_BATCH", body)

    def cluster_status(self) -> dict[str, Any]:
        status = self.rpc_json("RPC_CLUSTER_STATUS")
        self.current_node = str(status.get("self") or self.current_node or "")
        return status

    def data_plane_log(self, role: str | None = None) -> tuple[Path | None, str]:
        role = role or self.current_node or "A"
        candidates: list[Path] = []
        if os.environ.get("DP_LOG"):
            candidates.append(Path(os.environ["DP_LOG"]))
        candidates.extend([
            self.native_root / "logs" / f"dp_{role}.log",
            self.native_root / "logs" / "dp_A.log",
            self.native_root / "logs" / "dp_B.log",
        ])
        seen: set[Path] = set()
        for path in candidates:
            p = path.resolve()
            if p in seen:
                continue
            seen.add(p)
            if p.exists():
                text = p.read_text(encoding="utf-8", errors="replace")
                self.log(f"read data-plane log {p} bytes={len(text)}")
                return p, text
        return None, ""

    def run_cmd(self, argv: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
        self.log("cmd " + " ".join(argv))
        proc = subprocess.run(
            argv,
            cwd=str(self.repo_root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        self.log(f"cmd rc={proc.returncode} stdout={proc.stdout[-500:]} stderr={proc.stderr[-500:]}")
        return proc

    def finalize(self, result: CheckResult) -> int:
        status = result.status.upper()
        completion = result.completion or COMPLETION_BY_STATUS.get(status, "未完成")
        evidence = result.evidence or ["无关键证据"]
        record = {
            "module": self.module,
            "module_name": self.spec["module_name"],
            "fn_id": self.fn_id,
            "function": self.spec["name"],
            "source": self.spec["source"],
            "started_at": self.started_at,
            "finished_at": _now_iso(),
            "status": status,
            "passed": status == "PASS",
            "completion": completion,
            "evidence": evidence,
            "details": _json_safe(result.details),
            "env": {
                "UDS": self.uds,
                "CTRL_URL": self.ctrl_url,
                "REQUIRE_PEER": self.require_peer,
                "ALLOW_DESTRUCTIVE": self.allow_destructive,
                "CURRENT_NODE": self.current_node,
            },
            "log": str(self.run_log),
            "run_json": str(self.run_json),
            "raw_json": str(self.raw_json),
            "rpc_calls": self._raw_calls,
        }
        self.log(f"result={status} completion={completion}")
        self.run_log.write_text("\n".join(self._log_lines) + "\n", encoding="utf-8")
        self.run_json.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.raw_json.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.summary_md.write_text(self._summary_text(record), encoding="utf-8")
        print(f"{self.module}/{self.fn_id} {status} - {self.spec['name']}")
        for item in evidence:
            print(f"- {item}")
        print(f"summary: {self.summary_md}")
        print(f"log: {self.run_log}")
        return EXIT_CODES.get(status, 1)

    def _summary_text(self, record: dict[str, Any]) -> str:
        evidence_lines = "\n".join(f"- {item}" for item in record["evidence"])
        scope_lines = "\n".join(f"- {item}" for item in self.spec.get("scope", []))
        return (
            f"# {self.fn_id} Summary\n\n"
            f"- Module: {record['module_name']}\n"
            f"- Function: {record['function']}\n"
            f"- Source: {record['source']}\n"
            f"- Last Run: {record['finished_at']}\n"
            f"- Result: {record['status']}\n"
            f"- Completion: {record['completion']}\n"
            f"- Log: {record['log']}\n"
            f"- Raw: {record['raw_json']}\n\n"
            f"## 关键证据\n\n"
            f"{evidence_lines}\n\n"
            f"## 统计口径\n\n"
            f"{scope_lines}\n"
        )


def run_from_catalog(module: str, fn_id: str, fn_dir: Path) -> int:
    from .checks import run_check

    spec = get_spec(module, fn_id)
    ctx = FnContext(spec, fn_dir)
    try:
        result = run_check(str(spec["check"]), ctx)
    except CheckExit as exc:
        result = CheckResult(
            exc.status,
            [exc.evidence],
            exc.details,
            exc.completion,
        )
    except Exception as exc:
        ctx.log(f"unhandled exception: {exc!r}")
        result = fail_result(f"脚本异常: {exc}", details={"exception": repr(exc)})
    return ctx.finalize(result)


def main_entry(module: str, fn_id: str, file_path: str) -> None:
    raise SystemExit(run_from_catalog(module, fn_id, Path(file_path).resolve().parent))
