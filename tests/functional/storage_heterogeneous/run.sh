#!/usr/bin/env bash
# Run all sub-feature tests for the heterogeneous storage module.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

for t in test_*.py; do
    echo "========== $t =========="
    python3 "$t" || exit $?
done
echo "[DONE] storage_heterogeneous all PASS"
