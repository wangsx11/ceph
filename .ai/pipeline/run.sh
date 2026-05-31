#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PLAN_FILE="${SCRIPT_DIR}/plan.md"
STATE_FILE="${SCRIPT_DIR}/state.md"
CURRENT_FILE="${SCRIPT_DIR}/current_round"
REPORT_DIR="${SCRIPT_DIR}/reports"
PROMPT_DIR="${SCRIPT_DIR}/prompts"
LOG_DIR="${SCRIPT_DIR}/logs"
BLOCKED_FILE="${SCRIPT_DIR}/BLOCKED"
DONE_FILE="${SCRIPT_DIR}/DONE"
STOP_FILE="${SCRIPT_DIR}/STOP"
FAILED_FILE="${SCRIPT_DIR}/FAILED"

APPROVAL="${PIPELINE_APPROVAL:-never}"
SANDBOX="${PIPELINE_SANDBOX:-workspace-write}"
START_ROUND="${PIPELINE_START_ROUND:-}"
END_ROUND="${PIPELINE_END_ROUND:-5}"

mkdir -p "${REPORT_DIR}" "${PROMPT_DIR}" "${LOG_DIR}"

log() {
    printf '[pipeline] %s\n' "$*"
}

round_id() {
    printf 'round-%02d' "$1"
}

read_current_round() {
    if [ -n "${START_ROUND}" ]; then
        printf '%s\n' "${START_ROUND}"
        return
    fi
    if [ -f "${CURRENT_FILE}" ]; then
        tr -d '[:space:]' < "${CURRENT_FILE}"
        return
    fi
    printf '1\n'
}

compose_prompt() {
    local round="$1"
    local rid
    rid="$(round_id "${round}")"
    local round_prompt="${PROMPT_DIR}/${rid}.md"

    if [ ! -f "${round_prompt}" ]; then
        log "missing prompt: ${round_prompt}"
        exit 2
    fi

    cat <<EOF
# Automated Native RDMA Pipeline

You are running in a fresh non-interactive Codex exec session.

Repository root: ${REPO_ROOT}
Pipeline dir: ${SCRIPT_DIR}
Round: ${round}

Important:
- Do not assume prior chat history.
- Read the local files listed below.
- Keep context compact by relying on files, not chat memory.
- Preserve unrelated user changes in the dirty working tree.
- If blocked, create ${BLOCKED_FILE} with a short reason.
- Do not create ${DONE_FILE} except in Round 5 after final acceptance passes.

Required pipeline files:
- ${PLAN_FILE}
- ${STATE_FILE}

Previous reports, if present:
EOF

    local prev
    for prev in $(seq 1 $(( round - 1 ))); do
        printf -- '- %s/%s.md\n' "${REPORT_DIR}" "$(round_id "${prev}")"
    done

    cat <<EOF

Round-specific instructions:

EOF

    cat "${round_prompt}"

    cat <<EOF

End-of-round requirements:
- Update ${STATE_FILE}.
- Mention changed files and validation commands in the final response.
- Keep the final response concise enough for the next round to read.
- If you cannot continue safely, write ${BLOCKED_FILE}; otherwise leave it absent.
EOF
}

main() {
    if ! command -v codex >/dev/null 2>&1; then
        log "codex command not found"
        exit 127
    fi

    if [ -f "${STOP_FILE}" ]; then
        log "STOP file exists: ${STOP_FILE}"
        exit 0
    fi

    if [ -f "${BLOCKED_FILE}" ]; then
        log "BLOCKED file exists. Resolve it, remove it, then rerun."
        cat "${BLOCKED_FILE}" || true
        exit 3
    fi

    if [ -f "${DONE_FILE}" ]; then
        log "DONE file already exists: ${DONE_FILE}"
        exit 0
    fi

    local current
    current="$(read_current_round)"
    if ! [[ "${current}" =~ ^[0-9]+$ ]]; then
        log "invalid current round: ${current}"
        exit 2
    fi
    if ! [[ "${END_ROUND}" =~ ^[0-9]+$ ]]; then
        log "invalid end round: ${END_ROUND}"
        exit 2
    fi

    local round
    for round in $(seq "${current}" "${END_ROUND}"); do
        if [ -f "${STOP_FILE}" ]; then
            log "STOP file exists before round ${round}; stopping."
            exit 0
        fi
        if [ -f "${BLOCKED_FILE}" ]; then
            log "BLOCKED file exists before round ${round}; stopping."
            cat "${BLOCKED_FILE}" || true
            exit 3
        fi

        local rid prompt_file report_file stdout_log rc
        rid="$(round_id "${round}")"
        prompt_file="${LOG_DIR}/${rid}.prompt.md"
        report_file="${REPORT_DIR}/${rid}.md"
        stdout_log="${LOG_DIR}/${rid}.stdout.log"

        printf '%s\n' "${round}" > "${CURRENT_FILE}"
        rm -f "${FAILED_FILE}"
        compose_prompt "${round}" > "${prompt_file}"

        log "starting ${rid}"
        log "prompt=${prompt_file}"
        log "report=${report_file}"
        log "stdout=${stdout_log}"

        set +e
        codex --ask-for-approval "${APPROVAL}" exec \
            -C "${REPO_ROOT}" \
            --sandbox "${SANDBOX}" \
            --color never \
            -o "${report_file}" \
            - < "${prompt_file}" 2>&1 | tee "${stdout_log}"
        rc=${PIPESTATUS[0]}
        set -e

        if [ "${rc}" -ne 0 ]; then
            {
                printf 'round=%s\n' "${round}"
                printf 'exit_code=%s\n' "${rc}"
                printf 'stdout_log=%s\n' "${stdout_log}"
                printf 'report=%s\n' "${report_file}"
            } > "${FAILED_FILE}"
            log "${rid} failed with exit code ${rc}; see ${FAILED_FILE}"
            exit "${rc}"
        fi

        if [ ! -s "${report_file}" ]; then
            {
                printf 'round=%s\n' "${round}"
                printf 'reason=empty report file\n'
                printf 'stdout_log=%s\n' "${stdout_log}"
            } > "${FAILED_FILE}"
            log "${rid} finished but report is empty"
            exit 4
        fi

        if [ -f "${BLOCKED_FILE}" ]; then
            log "${rid} created BLOCKED; stopping."
            cat "${BLOCKED_FILE}" || true
            exit 3
        fi

        printf '%s\n' $(( round + 1 )) > "${CURRENT_FILE}"
        log "completed ${rid}"
    done

    if [ "${END_ROUND}" -ge 5 ]; then
        if [ -f "${DONE_FILE}" ]; then
            log "pipeline completed successfully"
        else
            log "round 5 finished but DONE was not created; check reports/state"
            exit 5
        fi
    else
        log "stopped after configured end round ${END_ROUND}"
    fi
}

main "$@"
