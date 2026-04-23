#!/usr/bin/env python3
"""librados single-thread sequential 1KB write latency benchmark on perf_pool."""

import rados
import time
import os
import numpy as np

POOL = "perf_pool"
CONF = "/etc/ceph/ceph.conf"
OBJ_SIZE = 1024  # 1KB
NUM_WRITES = 1000
OBJ_PREFIX = "perf_bench_"

def main():
    data = os.urandom(OBJ_SIZE)
    obj_names = [f"{OBJ_PREFIX}{i}" for i in range(NUM_WRITES)]

    cluster = rados.Rados(conffile=CONF)
    cluster.connect()
    ioctx = cluster.open_ioctx(POOL)

    latencies = []
    print(f"Writing {NUM_WRITES} x {OBJ_SIZE}B objects to {POOL} ...")

    for name in obj_names:
        t0 = time.monotonic()
        ioctx.write_full(name, data)
        elapsed = time.monotonic() - t0
        latencies.append(elapsed)

    lat = np.array(latencies) * 1000  # convert to ms

    print(f"\n{'='*40}")
    print(f" Results  ({NUM_WRITES} writes, {OBJ_SIZE}B each)")
    print(f"{'='*40}")
    print(f" Avg latency : {lat.mean():.3f} ms")
    print(f" Min latency : {lat.min():.3f} ms")
    print(f" Max latency : {lat.max():.3f} ms")
    print(f" P50         : {np.percentile(lat, 50):.3f} ms")
    print(f" P90         : {np.percentile(lat, 90):.3f} ms")
    print(f" P99         : {np.percentile(lat, 99):.3f} ms")
    print(f" P99.9       : {np.percentile(lat, 99.9):.3f} ms")
    print(f"{'='*40}")

    # Cleanup
    print("\nCleaning up test objects ...")
    for name in obj_names:
        try:
            ioctx.remove_object(name)
        except rados.ObjectNotFound:
            pass

    ioctx.close()
    cluster.shutdown()
    print("Done.")

if __name__ == "__main__":
    main()
