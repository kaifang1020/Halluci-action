#!/usr/bin/env bash
# =============================================================================
# run_experiment_codex.sh — Halluci-Action experiment entry point
#
# Usage:
#   ./run_experiment_codex.sh list
#   ./run_experiment_codex.sh S-1
#   ./run_experiment_codex.sh S-1 --agent gemini --model gemini-3.1-pro
#   ./run_experiment_codex.sh S-1 --no-codebook
#   ./run_experiment_codex.sh all
#   DOMAIN=sales ./run_experiment_codex.sh all
#   DOMAIN=inventory DIFFICULTY=medium ./run_experiment_codex.sh all
#
# Default agent: deepseek / deepseek-chat
# Default condition: codebook (use --no-codebook for explicit constraints)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/research/.env"

# ---------------------------------------------------------------------------
# Load API keys and connection config from research/.env
# ---------------------------------------------------------------------------
if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found."
    echo "Run: cp research/.env.example research/.env  and fill in your API keys."
    exit 1
fi
set -a
source "$ENV_FILE"
set +a

# Local Odoo/PostgreSQL endpoints must not go through HPC HTTP proxies.
LOCAL_NO_PROXY="localhost,127.0.0.1,::1"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}$LOCAL_NO_PROXY"
export no_proxy="${no_proxy:+$no_proxy,}$LOCAL_NO_PROXY"

# ---------------------------------------------------------------------------
# Defaults (override via environment or flags)
# ---------------------------------------------------------------------------
DEFAULT_AGENT="${DEFAULT_AGENT:-deepseek}"
DEFAULT_MODEL="${DEFAULT_MODEL:-deepseek-chat}"

# ---------------------------------------------------------------------------
# Parse first positional argument (task-id or "list" or "all")
# ---------------------------------------------------------------------------
TASK_ARG="${1:-}"
if [[ -z "$TASK_ARG" ]]; then
    echo "Usage: $0 <task-id|all|list> [--agent AGENT] [--model MODEL] [--no-codebook] [--kl KL1|KL2|KL3] [--runs N]"
    exit 1
fi
shift

# ---------------------------------------------------------------------------
# list: show available tasks and exit
# ---------------------------------------------------------------------------
if [[ "$TASK_ARG" == "list" ]]; then
    conda run -n odoo-research --no-capture-output \
        python3 -m research.harness list-tasks "$@"
    exit 0
fi

# ---------------------------------------------------------------------------
# Parse remaining flags (passed through to harness)
# ---------------------------------------------------------------------------
AGENT="$DEFAULT_AGENT"
MODEL="$DEFAULT_MODEL"
EXTRA_FLAGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent)   AGENT="$2";  shift 2 ;;
        --model)   MODEL="$2";  shift 2 ;;
        *)         EXTRA_FLAGS+=("$1"); shift ;;
    esac
done

# ---------------------------------------------------------------------------
# Helper: run a single task
# ---------------------------------------------------------------------------
run_task() {
    local task_id="$1"
    echo
    echo "========================================"
    echo "Task: $task_id | Agent: $AGENT | Model: $MODEL"
    echo "========================================"
    conda run -n odoo-research --no-capture-output \
        python3 -m research.harness run \
            --agent "$AGENT" \
            --model "$MODEL" \
            --task-id "$task_id" \
            "${EXTRA_FLAGS[@]+"${EXTRA_FLAGS[@]}"}"
}

# ---------------------------------------------------------------------------
# all: run every task (optionally filtered by DOMAIN / DIFFICULTY)
# ---------------------------------------------------------------------------
if [[ "$TASK_ARG" == "all" ]]; then
    FILTER_ARGS=()
    [[ -n "${DOMAIN:-}"     ]] && FILTER_ARGS+=(--domain "$DOMAIN")
    [[ -n "${DIFFICULTY:-}" ]] && FILTER_ARGS+=(--difficulty "$DIFFICULTY")

    TASK_IDS=$(conda run -n odoo-research --no-capture-output \
        python3 -m research.harness list-tasks "${FILTER_ARGS[@]+"${FILTER_ARGS[@]}"}" 2>/dev/null \
        | awk '/^[A-Z]+-[0-9]+/{print $1}')

    if [[ -z "$TASK_IDS" ]]; then
        echo "No tasks found for the given filters."
        exit 1
    fi

    for tid in $TASK_IDS; do
        run_task "$tid"
    done
    exit 0
fi

# ---------------------------------------------------------------------------
# Single task
# ---------------------------------------------------------------------------
run_task "$TASK_ARG"
