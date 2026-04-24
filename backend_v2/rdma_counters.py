# -*- coding: utf-8 -*-
"""Read real RDMA counters under /sys/class/infiniband.

Counter files are scaled by 4 to yield bytes (per IB spec's 4-byte word).
We sample at arbitrary wall-clock interval and return deltas.
"""
import os
import threading
import time

from config import LINK_BW_MBPS


class RdmaCounters:
    def __init__(self):
        self._lock = threading.Lock()
        self._prev = None

    @staticmethod
    def _find_dev():
        base = "/sys/class/infiniband"
        if not os.path.isdir(base):
            return None
        for d in os.listdir(base):
            if os.path.exists(f"{base}/{d}/ports/1/counters/port_rcv_data"):
                return f"{base}/{d}/ports/1/counters"
        return None

    def sample(self):
        """Return (rcv_mbps, xmit_mbps, util_pct) or (None, None, None)."""
        path = self._find_dev()
        if not path:
            return None, None, None
        try:
            with open(f"{path}/port_rcv_data") as f:
                rcv = int(f.read().strip()) * 4
            with open(f"{path}/port_xmit_data") as f:
                xmt = int(f.read().strip()) * 4
        except Exception:
            return None, None, None

        now = time.time()
        with self._lock:
            if self._prev is None:
                self._prev = (now, rcv, xmt)
                return None, None, None
            pt, pr, px = self._prev
            dt = now - pt
            if dt < 0.05:
                return None, None, None
            self._prev = (now, rcv, xmt)

        rcv_mbps = (rcv - pr) / dt / 1_048_576
        xmt_mbps = (xmt - px) / dt / 1_048_576
        util = (xmt_mbps + rcv_mbps) / (2.0 * LINK_BW_MBPS) * 100
        return round(rcv_mbps, 2), round(xmt_mbps, 2), round(util, 2)


counters = RdmaCounters()
