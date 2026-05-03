from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path


def can_connect_uds(uds: str, timeout_s: float = 0.2) -> bool:
    p = Path(uds)
    if not p.is_socket():
        return False
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        sock.connect(uds)
        return True
    except OSError:
        return False
    finally:
        sock.close()


def ensure_cmake_target(root: Path, target: str) -> Path:
    build_dir = Path(os.environ.get("PERF_BUILD_DIR", root / "native_rdma" / "build-current")).resolve()
    bin_path = build_dir / "bin" / target
    if bin_path.exists() and os.access(bin_path, os.X_OK):
        return bin_path
    native_root = root / "native_rdma"
    subprocess.run(
        ["cmake", "-S", str(native_root), "-B", str(build_dir), "-DCMAKE_BUILD_TYPE=Release", "-GNinja"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    subprocess.run(
        ["cmake", "--build", str(build_dir), "--target", target, "-j"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return bin_path


def resolve_cmake_bin(root: Path, target: str) -> Path:
    override = os.environ.get(f"{target.upper()}_BIN")
    if override:
        return Path(override).resolve()
    current = root / "native_rdma" / "build-current" / "bin" / target
    if current.exists() and os.access(current, os.X_OK):
        return current
    old = root / "native_rdma" / "build" / "bin" / target
    if old.exists() and os.access(old, os.X_OK):
        return old
    return ensure_cmake_target(root, target)
