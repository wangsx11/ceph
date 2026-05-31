#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PROMPT_FILE="${SCRIPT_DIR}/prompts/perf_all_pf_fast_ui_fix.md"
REPORT_FILE="${SCRIPT_DIR}/reports/perf_all_pf_fast_ui_fix.md"
STDOUT_LOG="${SCRIPT_DIR}/logs/perf_all_pf_fast_ui_fix.stdout.log"
FAILED_FILE="${SCRIPT_DIR}/FAILED"
BLOCKED_FILE="${SCRIPT_DIR}/BLOCKED"
DONE_FILE="${SCRIPT_DIR}/PERF_ALL_PF_FAST_UI_FIX_DONE"

APPROVAL="${PIPELINE_APPROVAL:-never}"
SANDBOX="${PIPELINE_SANDBOX:-workspace-write}"

mkdir -p "${SCRIPT_DIR}/reports" "${SCRIPT_DIR}/logs"
rm -f "${FAILED_FILE}" "${BLOCKED_FILE}" "${DONE_FILE}"

if [ ! -f "${PROMPT_FILE}" ]; then
    printf '[perf-all-pf-fast-ui-fix] missing prompt: %s\n' "${PROMPT_FILE}" >&2
    exit 2
fi

printf '[perf-all-pf-fast-ui-fix] repo=%s\n' "${REPO_ROOT}"
printf '[perf-all-pf-fast-ui-fix] prompt=%s\n' "${PROMPT_FILE}"
printf '[perf-all-pf-fast-ui-fix] report=%s\n' "${REPORT_FILE}"
printf '[perf-all-pf-fast-ui-fix] stdout=%s\n' "${STDOUT_LOG}"

set +e
codex --ask-for-approval "${APPROVAL}" exec \
    -C "${REPO_ROOT}" \
    --sandbox "${SANDBOX}" \
    --color never \
    -o "${REPORT_FILE}" \
    - < "${PROMPT_FILE}" 2>&1 | tee "${STDOUT_LOG}"
rc=${PIPESTATUS[0]}
set -e

if [ "${rc}" -ne 0 ]; then
    {
        printf 'script=run_perf_all_pf_fast_ui_fix.sh\n'
        printf 'exit_code=%s\n' "${rc}"
        printf 'stdout_log=%s\n' "${STDOUT_LOG}"
        printf 'report=%s\n' "${REPORT_FILE}"
    } > "${FAILED_FILE}"
    printf '[perf-all-pf-fast-ui-fix] codex failed with exit code %s; see %s\n' "${rc}" "${FAILED_FILE}" >&2
    exit "${rc}"
fi

if [ ! -s "${REPORT_FILE}" ]; then
    {
        printf 'script=run_perf_all_pf_fast_ui_fix.sh\n'
        printf 'reason=empty report file\n'
        printf 'stdout_log=%s\n' "${STDOUT_LOG}"
    } > "${FAILED_FILE}"
    printf '[perf-all-pf-fast-ui-fix] empty report file\n' >&2
    exit 4
fi

if [ -f "${BLOCKED_FILE}" ]; then
    printf '[perf-all-pf-fast-ui-fix] blocked:\n' >&2
    cat "${BLOCKED_FILE}" >&2 || true
    exit 3
fi

if [ ! -f "${DONE_FILE}" ]; then
    printf '[perf-all-pf-fast-ui-fix] missing %s; check report\n' "${DONE_FILE}" >&2
    exit 5
fi

printf '[perf-all-pf-fast-ui-fix] completed. Report: %s\n' "${REPORT_FILE}"
