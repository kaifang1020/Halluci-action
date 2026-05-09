#!/usr/bin/env bash
# =============================================================================
# Halluci-Action Experiment Runner
# =============================================================================
#
# This script is a reusable wrapper around `python -m research.harness`.
# Task IDs are discovered dynamically from research.tasks.TASKS, so adding a
# task to the registry automatically makes it available here.
#
# Examples:
#   ./run_experiment.sh list
#   ./run_experiment.sh S-1
#   ./run_experiment.sh all
#   DOMAIN=sales ./run_experiment.sh all
#   DOMAIN=inventory DIFFICULTY=medium ./run_experiment.sh all
#   ./run_experiment.sh --no-reset PU-2 deepseek-reasoner
#
# Environment:
#   AGENT=deepseek|openai|anthropic|claude|kimi|qwen
#   MODEL=deepseek-chat
#   KL=KL1|KL2|KL3
#   MAX_STEPS=15
#   RUNS=1
#   DOMAIN=sales|inventory|accounting|crm|pos|hr|helpdesk|purchase|manufacturing|project
#   DIFFICULTY=easy|medium|hard|comprehensive
#   PYTHON=python3
#
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

LOCAL_NO_PROXY="localhost,127.0.0.1,::1"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}$LOCAL_NO_PROXY"
export no_proxy="${no_proxy:+$no_proxy,}$LOCAL_NO_PROXY"

PYTHON="${PYTHON:-python3}"
AGENT="${AGENT:-deepseek}"
MODEL="${MODEL:-deepseek-chat}"
KL="${KL:-KL1}"
MAX_STEPS="${MAX_STEPS:-15}"
RUNS="${RUNS:-1}"
DOMAIN="${DOMAIN:-}"
DIFFICULTY="${DIFFICULTY:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage:
  ./run_experiment.sh list
  ./run_experiment.sh TASK_ID [MODEL]
  ./run_experiment.sh all [MODEL]

Examples:
  ./run_experiment.sh S-1
  ./run_experiment.sh PU-2 deepseek-reasoner
  ./run_experiment.sh --no-reset all
  DOMAIN=sales ./run_experiment.sh all
  DOMAIN=inventory DIFFICULTY=medium ./run_experiment.sh all

Options:
  --no-reset      Do not reset/reseed before running.
  --help, -h      Show this help.

Environment:
  AGENT=$AGENT
  MODEL=$MODEL
  KL=$KL
  MAX_STEPS=$MAX_STEPS
  RUNS=$RUNS
  DOMAIN=${DOMAIN:-<unset>}
  DIFFICULTY=${DIFFICULTY:-<unset>}
  PYTHON=$PYTHON
EOF
}

print_header() {
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Halluci-Action Experiment Runner${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
}

check_api_key() {
    case "$AGENT" in
        deepseek)
            if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
                echo -e "${RED}Error: DEEPSEEK_API_KEY not set${NC}"
                exit 1
            fi
            ;;
        openai)
            if [ -z "${OPENAI_API_KEY:-}" ]; then
                echo -e "${RED}Error: OPENAI_API_KEY not set${NC}"
                exit 1
            fi
            ;;
        anthropic|claude)
            if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
                echo -e "${RED}Error: ANTHROPIC_API_KEY not set${NC}"
                exit 1
            fi
            ;;
        kimi)
            if [ -z "${MOONSHOT_API_KEY:-}" ]; then
                echo -e "${RED}Error: MOONSHOT_API_KEY not set${NC}"
                exit 1
            fi
            ;;
        qwen)
            if [ -z "${DASHSCOPE_API_KEY:-}" ]; then
                echo -e "${RED}Error: DASHSCOPE_API_KEY not set${NC}"
                exit 1
            fi
            ;;
        *)
            echo -e "${RED}Error: unsupported AGENT '$AGENT'${NC}"
            exit 1
            ;;
    esac
}

task_ids() {
    DOMAIN="$DOMAIN" DIFFICULTY="$DIFFICULTY" "$PYTHON" - <<'PY'
import os
from research.tasks import TASKS

domain = os.environ.get("DOMAIN") or None
difficulty = os.environ.get("DIFFICULTY") or None

for task_id, task in TASKS.items():
    if domain and task.get("domain") != domain:
        continue
    if difficulty and task.get("difficulty") != difficulty:
        continue
    print(task_id)
PY
}

list_tasks() {
    DOMAIN="$DOMAIN" DIFFICULTY="$DIFFICULTY" "$PYTHON" - <<'PY'
import os
from research.tasks import TASKS

domain = os.environ.get("DOMAIN") or None
difficulty = os.environ.get("DIFFICULTY") or None

rows = []
for task_id, task in TASKS.items():
    if domain and task.get("domain") != domain:
        continue
    if difficulty and task.get("difficulty") != difficulty:
        continue
    rows.append((task_id, task.get("domain", ""), task.get("difficulty", ""), task["name"]))

print(f"Available tasks: {len(rows)}")
if domain or difficulty:
    print(f"Filters: domain={domain or '*'}, difficulty={difficulty or '*'}")
print()
for task_id, task_domain, task_difficulty, name in rows:
    print(f"{task_id:6s} {task_domain:15s} {task_difficulty:14s} {name}")
PY
}

task_exists() {
    local task_id="$1"
    TASK_ID="$task_id" "$PYTHON" - <<'PY'
import os
import sys
from research.tasks import get_task

try:
    get_task(os.environ["TASK_ID"])
except ValueError:
    sys.exit(1)
sys.exit(0)
PY
}

reset_database() {
    echo -e "${YELLOW}Resetting database to initial state...${NC}"
    "$PYTHON" potential_scripts/reset_database.py
    echo ""
    echo -e "${YELLOW}Seeding database with benchmark data...${NC}"
    "$PYTHON" scripts/furnish_database.py
    echo ""
    echo -e "${GREEN}Database ready${NC}"
    echo ""
}

run_task() {
    local task_id="$1"

    echo -e "${YELLOW}Running: $task_id${NC}"
    echo "Agent: $AGENT | Model: $MODEL | KL: $KL | Runs: $RUNS | Max steps: $MAX_STEPS"
    echo ""

    "$PYTHON" -m research.harness run \
        --agent "$AGENT" \
        --model "$MODEL" \
        --task-id "$task_id" \
        --kl "$KL" \
        --max-steps "$MAX_STEPS" \
        --runs "$RUNS"

    echo ""
    echo -e "${GREEN}Completed: $task_id${NC}"
    echo ""
}

NO_RESET=false
TARGET=""
MODEL_ARG=""

for arg in "$@"; do
    case "$arg" in
        --no-reset)
            NO_RESET=true
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        list|--list|-l)
            list_tasks
            exit 0
            ;;
        all|--all)
            TARGET="all"
            ;;
        -*)
            echo -e "${RED}Unknown option: $arg${NC}"
            usage
            exit 1
            ;;
        *)
            if [ -z "$TARGET" ]; then
                TARGET="$arg"
            elif [ -z "$MODEL_ARG" ]; then
                MODEL_ARG="$arg"
            else
                echo -e "${RED}Unexpected argument: $arg${NC}"
                usage
                exit 1
            fi
            ;;
    esac
done

if [ -n "$MODEL_ARG" ]; then
    MODEL="$MODEL_ARG"
fi

if [ -z "$TARGET" ]; then
    usage
    exit 0
fi

if [ "$TARGET" = "all" ]; then
    mapfile -t TASKS_TO_RUN < <(task_ids)
    if [ "${#TASKS_TO_RUN[@]}" -eq 0 ]; then
        echo -e "${RED}No tasks match DOMAIN='${DOMAIN}' DIFFICULTY='${DIFFICULTY}'${NC}"
        exit 1
    fi

    print_header
    check_api_key

    echo -e "${YELLOW}Running ${#TASKS_TO_RUN[@]} task(s).${NC}"
    if [ -n "$DOMAIN" ] || [ -n "$DIFFICULTY" ]; then
        echo "Filters: DOMAIN=${DOMAIN:-*} DIFFICULTY=${DIFFICULTY:-*}"
    fi
    echo ""

    for task_id in "${TASKS_TO_RUN[@]}"; do
        if [ "$NO_RESET" = false ]; then
            reset_database
        fi
        run_task "$task_id"
    done
else
    if ! task_exists "$TARGET"; then
        echo -e "${RED}Unknown task ID: $TARGET${NC}"
        echo ""
        list_tasks
        exit 1
    fi

    print_header
    check_api_key

    if [ "$NO_RESET" = false ]; then
        reset_database
    fi
    run_task "$TARGET"
fi

echo -e "${GREEN}Results saved in: research/experiments/runs/${NC}"
