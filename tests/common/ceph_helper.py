# -*- coding: utf-8 -*-
"""Ceph / RDMA test common helpers.

All functional & performance test scripts import from here.
Keeping one dependency surface makes the suite portable across nodes.
"""
import os
import subprocess
import sys
import time
from contextlib import contextmanager

DEFAULT_CONF = os.environ.get("CEPH_CONF", "/etc/ceph/ceph.conf")
DEFAULT_USER = os.environ.get("CEPH_USER", "client.admin")
FALLBACK_POOL = os.environ.get("CEPH_TEST_FALLBACK_POOL", "testbench")


def die(msg, code=1):
    sys.stderr.write(f"[FAIL] {msg}\n")
    sys.exit(code)


def info(msg):
    sys.stdout.write(f"[INFO] {msg}\n")
    sys.stdout.flush()


def ok(msg):
    sys.stdout.write(f"[ OK ] {msg}\n")
    sys.stdout.flush()


def run(cmd, check=True, timeout=300, capture=True):
    """Thin wrapper over subprocess, returns (rc, stdout, stderr)."""
    if isinstance(cmd, str):
        shell = True
    else:
        shell = False
    p = subprocess.run(
        cmd, shell=shell, timeout=timeout,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    out = p.stdout.decode("utf-8", "ignore") if p.stdout else ""
    err = p.stderr.decode("utf-8", "ignore") if p.stderr else ""
    if check and p.returncode != 0:
        die(f"cmd failed ({p.returncode}): {cmd}\n{err}", code=3)
    return p.returncode, out, err


def need_bin(name):
    rc, _, _ = run(f"command -v {name}", check=False)
    if rc != 0:
        die(f"required tool `{name}` not found in PATH", code=2)


def _resolve_physical_pool(cluster, pool):
    if cluster.pool_exists(pool):
        return pool, None

    if FALLBACK_POOL and pool != FALLBACK_POOL and cluster.pool_exists(FALLBACK_POOL):
        return FALLBACK_POOL, pool

    cluster.create_pool(pool)
    return pool, None


def open_ioctx(cluster, pool):
    physical_pool, namespace = _resolve_physical_pool(cluster, pool)
    ioctx = cluster.open_ioctx(physical_pool)
    if namespace:
        ioctx.set_namespace(namespace)
    return ioctx


def connect_rados(pool):
    try:
        import rados
    except ImportError:
        die("python3-rados module missing (apt install python3-rados)", code=2)
    cluster = rados.Rados(conffile=DEFAULT_CONF, name=DEFAULT_USER)
    cluster.connect(timeout=10)
    return cluster, open_ioctx(cluster, pool)


@contextmanager
def rados_pool(pool):
    cluster, ioctx = connect_rados(pool)
    try:
        yield cluster, ioctx
    finally:
        ioctx.close()
        cluster.shutdown()


def rdma_available():
    """Return True if at least one IB/RoCE device is present."""
    path = "/sys/class/infiniband"
    if not os.path.isdir(path):
        return False
    return len(os.listdir(path)) > 0


def rdma_port_rate_gbps():
    """Best-effort read of the first IB port link rate in Gbps."""
    base = "/sys/class/infiniband"
    if not os.path.isdir(base):
        return None
    for dev in os.listdir(base):
        rate_file = f"{base}/{dev}/ports/1/rate"
        if os.path.exists(rate_file):
            with open(rate_file) as f:
                # example: "100 Gb/sec (4X EDR)"
                return float(f.read().split()[0])
    return None


def ceph_ms_type():
    """Query the active messenger type to confirm RDMA is on."""
    rc, out, _ = run("ceph config get global ms_type", check=False)
    return out.strip() if rc == 0 else "unknown"


def assert_ge(actual, target, label, unit=""):
    if actual >= target:
        ok(f"{label}: {actual:.2f}{unit} >= {target}{unit}")
        return True
    die(f"{label}: {actual:.2f}{unit} < {target}{unit} (target NOT met)")


def assert_le(actual, target, label, unit=""):
    if actual <= target:
        ok(f"{label}: {actual:.2f}{unit} <= {target}{unit}")
        return True
    die(f"{label}: {actual:.2f}{unit} > {target}{unit} (target NOT met)")


def time_block():
    return time.perf_counter()
