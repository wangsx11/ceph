#!/usr/bin/env bash
# Run all sub-feature tests for the heterogeneous storage module.
# set -e
# HERE="$(cd "$(dirname "$0")" && pwd)"
# cd "$HERE"

# for t in test_*.py; do
#     echo "========== $t =========="
#     python3 "$t" || exit $?
# done
# echo "[DONE] storage_heterogeneous all PASS"

#!/usr/bin/env bash
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

failed=0
for t in test_*.py; do
    echo "========== $t =========="
    python3 "$t" || { echo "FAILED: $t"; failed=$((failed + 1)); }
done

if [ $failed -gt 0 ]; then
    echo "[DONE] $failed test(s) FAILED"
    exit 1
fi
echo "[DONE] storage_heterogeneous all PASS"
