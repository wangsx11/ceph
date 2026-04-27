#!/usr/bin/env python3
"""
HTTP-level bench: hammers /api/kv/put on the control-plane so the
dashboard charts (ops/s, bw_tx_gbps, lat_*) visibly move.

Usage:
    python3 scripts/bench/bench_http.py \
        --url=http://localhost:5000 --threads=8 --duration=30 --val-size=256
"""
import argparse
import json
import threading
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url",      default="http://localhost:5000")
    ap.add_argument("--threads",  type=int, default=8)
    ap.add_argument("--duration", type=int, default=30)
    ap.add_argument("--val-size", type=int, default=256)
    ap.add_argument("--op",       choices=["put", "get", "mix"], default="put")
    ap.add_argument("--keyspace", type=int, default=10000)
    return ap.parse_args()


def put_once(base, tid, cnt, val):
    key = f"bk_{tid}_{cnt}"
    data = json.dumps({"key": key, "val": val}).encode()
    req = urllib.request.Request(
        f"{base}/api/kv/put",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5).read()


def get_once(base, tid, cnt):
    key = f"bk_{tid}_{cnt}"
    urllib.request.urlopen(f"{base}/api/kv/get?key={key}", timeout=5).read()


def worker(args, tid, stop_at, stats):
    val = "X" * args.val_size
    cnt = 0
    lats = []
    ok = err = 0
    while time.monotonic() < stop_at:
        kid = (tid * 1000003 + cnt) % args.keyspace
        t0 = time.perf_counter()
        try:
            if args.op == "put":
                put_once(args.url, tid, kid, val)
            elif args.op == "get":
                get_once(args.url, tid, kid)
            else:  # mix 80/20
                if (cnt & 7) < 6:
                    put_once(args.url, tid, kid, val)
                else:
                    get_once(args.url, tid, kid)
            ok += 1
            lats.append((time.perf_counter() - t0) * 1e6)  # us
        except (urllib.error.URLError, OSError):
            err += 1
        cnt += 1
    stats[tid] = (ok, err, lats)


def percentile(samples, q):
    if not samples:
        return 0.0
    k = int(len(samples) * q)
    if k >= len(samples):
        k = len(samples) - 1
    return samples[k]


def main():
    args = parse_args()
    print(f"[bench_http] url={args.url} op={args.op} threads={args.threads} "
          f"duration={args.duration}s val_size={args.val_size}")
    stop_at = time.monotonic() + args.duration
    stats = [None] * args.threads
    threads = []
    t_start = time.monotonic()
    for i in range(args.threads):
        t = threading.Thread(target=worker, args=(args, i, stop_at, stats))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t_start

    ok = sum(s[0] for s in stats)
    err = sum(s[1] for s in stats)
    lats = []
    for s in stats:
        lats.extend(s[2])
    lats.sort()

    avg = sum(lats) / len(lats) if lats else 0.0
    print("\n==== bench_http result ====")
    print(f"  elapsed   : {elapsed:.2f} s")
    print(f"  ops ok/err: {ok} / {err}")
    print(f"  ops/s     : {ok / elapsed:.0f}")
    print(f"  latency us: avg={avg:.1f}  p50={percentile(lats, 0.50):.1f}  "
          f"p95={percentile(lats, 0.95):.1f}  p99={percentile(lats, 0.99):.1f}  "
          f"p999={percentile(lats, 0.999):.1f}  "
          f"max={lats[-1] if lats else 0:.1f}")


if __name__ == "__main__":
    main()
