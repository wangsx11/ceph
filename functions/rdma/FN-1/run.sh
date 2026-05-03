#!/usr/bin/env bash
set -euo pipefail
FN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$FN_DIR/../../common/run_one.sh" "$FN_DIR" "$@"

