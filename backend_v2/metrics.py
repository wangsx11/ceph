# -*- coding: utf-8 -*-
"""Low-overhead metric primitives.

* `AtomicCounter` — thread-safe integer counter using `threading.Lock` (GIL
  guarantees atomic increments for ints, but we still need a lock for
  compound read-then-reset). Uses `array.array` for 64-bit counters.
* `LatencyHist`  — ring buffer of microsecond samples, O(1) insert,
  quantile computed by `np.partition` when `numpy` is available, else
  `sorted`.
"""
import threading
import time
from array import array


class AtomicCounter:
    __slots__ = ("_v", "_lk")

    def __init__(self):
        self._v = 0
        self._lk = threading.Lock()

    def add(self, n=1):
        with self._lk:
            self._v += n

    def get_and_reset(self):
        with self._lk:
            v, self._v = self._v, 0
            return v

    def get(self):
        return self._v


class LatencyHist:
    """Fixed-capacity ring buffer for latency samples (μs, float32)."""

    def __init__(self, cap=200_000):
        self._cap = cap
        self._buf = array("f", [0.0] * cap)
        self._head = 0
        self._size = 0
        self._lk = threading.Lock()

    def add(self, us):
        with self._lk:
            self._buf[self._head] = us
            self._head = (self._head + 1) % self._cap
            if self._size < self._cap:
                self._size += 1

    def snapshot(self):
        with self._lk:
            if self._size < self._cap:
                return list(self._buf[: self._size])
            return list(self._buf)

    def summary(self):
        data = self.snapshot()
        if not data:
            return {"n": 0, "avg": 0, "p50": 0, "p90": 0, "p99": 0}
        data.sort()
        n = len(data)

        def pct(p):
            idx = min(int(n * p / 100), n - 1)
            return data[idx]

        return {
            "n": n,
            "avg": sum(data) / n,
            "p50": pct(50),
            "p90": pct(90),
            "p99": pct(99),
        }


def now_us():
    return time.perf_counter() * 1_000_000
