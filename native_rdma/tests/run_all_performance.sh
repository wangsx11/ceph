#!/usr/bin/env bash
set -euo pipefail
# Top-level performance test entry point. Delegates to the W5 matrix driver.
# See docs/自研实施清单.md §7 for the threshold table.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$ROOT/tests/performance/run_all.sh" "$@"
