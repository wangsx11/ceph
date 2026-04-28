#!/usr/bin/env bash
# Perf #8: Discrete-event simulation engine throughput.
# Target per docs/自研实施清单.md §7 row #8: 100k entities, 1M events
# completed at >= 1x realtime (speedup >= 1.0).
#
# We send RPC_SIM_RUN over the data plane's UDS. The DP spawns N worker
# threads, runs the event loop, and returns a JSON report we pass through.
#
# Parameters (env):
#   ENTITIES  default 100000 (spec §7 row #8 target scale)
#   EVENTS    default 1000000
#   THREADS   default 4
#   STEP_US   default 10     (simulated us per event)
#   STRESS    default 32     (inner LCG iterations per event: models real
#                             DES per-event cost; ~150 ns of pure math)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
UDS="${UDS:-/tmp/native_rdma-dp.sock}"
ENTITIES="${ENTITIES:-100000}"
EVENTS="${EVENTS:-1000000}"
THREADS="${THREADS:-4}"
STEP_US="${STEP_US:-10}"
STRESS="${STRESS:-32}"
OUT_DIR="${OUT_DIR:-$ROOT/logs/perf}"
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/perf_08_simulation_${TS}.json"

[ -S "$UDS" ] || { echo "data plane not running (no $UDS)" >&2; exit 2; }

echo ">>> perf#8 sim run: entities=$ENTITIES events=$EVENTS threads=$THREADS step_us=$STEP_US stress=$STRESS" >&2

# Talk the UDS wire protocol: [u32 kind_len][kind][u32 body_len][body] ->
# [u32 resp_len][resp]. Python does struct packing + read.
resp=$(python3 - "$UDS" "$ENTITIES" "$EVENTS" "$THREADS" "$STEP_US" "$STRESS" <<'PY'
import socket, struct, sys
uds, ent, evt, thr, step, stress = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
kind = b"RPC_SIM_RUN"
body = f"entities={ent}&events={evt}&threads={thr}&step_us={step}&stress={stress}".encode()
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(600)   # sim may take tens of seconds for 10M events
s.connect(uds)
s.sendall(struct.pack("<I", len(kind)) + kind +
          struct.pack("<I", len(body)) + body)
def recv_n(n):
    out = b""
    while len(out) < n:
        b = s.recv(n - len(out))
        if not b: break
        out += b
    return out
hdr = recv_n(4)
(rl,) = struct.unpack("<I", hdr)
payload = recv_n(rl).decode(errors="replace")
s.close()
sys.stdout.write(payload)
PY
)

echo "  raw response: $resp" >&2

python3 - "$OUT" "$resp" <<'PY'
import json, sys
out_path, raw = sys.argv[1], sys.argv[2]
try:
    r = json.loads(raw)
except Exception as e:
    r = {"ok": False, "err": f"parse failed: {e}", "raw": raw}
speedup  = float(r.get("speedup", 0))
eps      = float(r.get("events_per_sec", 0))
passed   = bool(r.get("ok", False)) and speedup >= 1.0
result = {
    "metric":       "perf_08_simulation",
    "entities":     r.get("entities", 0),
    "events":       r.get("events", 0),
    "threads":      r.get("threads", 0),
    "step_us":      r.get("step_us", 0),
    "stress":       r.get("stress", 0),
    "wall_s":       r.get("wall_s", 0),
    "sim_s":        r.get("sim_s", 0),
    "speedup":      speedup,
    "events_per_sec": eps,
    "threshold_speedup": 1.0,
    "passed":       passed,
    "raw":          r,
}
with open(out_path, "w") as f: json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
PY
echo "[done] $OUT"
