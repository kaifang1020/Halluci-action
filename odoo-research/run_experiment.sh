#!/bin/bash
# =============================================================================
# Halluci-Action Experiment Runner
# =============================================================================
#
# This script runs trajectory generation experiments with LLM agents.
#
# SETUP:
#   1. Export your API key:
#      export DEEPSEEK_API_KEY=sk-your-key-here
#      # OR for other providers:
#      export OPENAI_API_KEY=sk-your-key-here
#      export ANTHROPIC_API_KEY=sk-your-key-here
#      export MOONSHOT_API_KEY=your-key-here  # For Kimi
#      export DASHSCOPE_API_KEY=your-key-here  # For Qwen
#
#   2. Ensure Odoo is running:
#      docker compose up -d
#
# USAGE:
#   ./run_experiment.sh                    # Run all tasks with default settings
#   ./run_experiment.sh task1              # Run specific task
#   ./run_experiment.sh task1 deepseek-reasoner  # Run with reasoning model
#   ./run_experiment.sh --no-reset task1   # Skip database reset
#
# =============================================================================

set -e

# Default settings
AGENT="${AGENT:-deepseek}"
MODEL="${MODEL:-deepseek-chat}"
KL="${KL:-KL1}"
MAX_STEPS="${MAX_STEPS:-15}"
RUNS="${RUNS:-1}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Halluci-Action Experiment Runner${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check API key
check_api_key() {
    case $AGENT in
        deepseek)
            if [ -z "$DEEPSEEK_API_KEY" ]; then
                echo -e "${RED}Error: DEEPSEEK_API_KEY not set${NC}"
                echo "Run: export DEEPSEEK_API_KEY=sk-your-key-here"
                exit 1
            fi
            echo -e "${GREEN}✓ DEEPSEEK_API_KEY is set${NC}"
            ;;
        openai)
            if [ -z "$OPENAI_API_KEY" ]; then
                echo -e "${RED}Error: OPENAI_API_KEY not set${NC}"
                exit 1
            fi
            echo -e "${GREEN}✓ OPENAI_API_KEY is set${NC}"
            ;;
        anthropic|claude)
            if [ -z "$ANTHROPIC_API_KEY" ]; then
                echo -e "${RED}Error: ANTHROPIC_API_KEY not set${NC}"
                exit 1
            fi
            echo -e "${GREEN}✓ ANTHROPIC_API_KEY is set${NC}"
            ;;
        kimi)
            if [ -z "$MOONSHOT_API_KEY" ]; then
                echo -e "${RED}Error: MOONSHOT_API_KEY not set${NC}"
                exit 1
            fi
            echo -e "${GREEN}✓ MOONSHOT_API_KEY is set${NC}"
            ;;
        qwen)
            if [ -z "$DASHSCOPE_API_KEY" ]; then
                echo -e "${RED}Error: DASHSCOPE_API_KEY not set${NC}"
                exit 1
            fi
            echo -e "${GREEN}✓ DASHSCOPE_API_KEY is set${NC}"
            ;;
    esac
}

# List available tasks
list_tasks() {
    echo -e "${YELLOW}Available tasks:${NC}"
    echo "  task1 - Process Samsung Galaxy S24 Order"
    echo "  task2 - Check Dyson Bulk Order Feasibility"
    echo "  task3 - Process USB-C Cable Return"
    echo "  task4 - Update USB-C Charger Prices"
    echo "  task5 - New Customer Order"
    echo "  task6 - End-of-Day Reconciliation"
    echo ""
}

# Run a single task
run_task() {
    local task_id=$1
    echo -e "${YELLOW}Running: $task_id${NC}"
    echo "Agent: $AGENT | Model: $MODEL | KL: $KL"
    echo ""

    python -m research.harness run \
        --agent "$AGENT" \
        --model "$MODEL" \
        --task-id "$task_id" \
        --kl "$KL" \
        --max-steps "$MAX_STEPS" \
        --runs "$RUNS"

    echo ""
    echo -e "${GREEN}✓ Completed: $task_id${NC}"
    echo ""
}

# Reset database to initial state
reset_database() {
    echo -e "${YELLOW}Resetting database to initial state...${NC}"
    python potential_scripts/reset_database.py
    echo ""
    echo -e "${YELLOW}Re-furnishing database with test data...${NC}"
    python potential_scripts/furnish_database.py
    echo ""
    echo -e "${GREEN}✓ Database ready${NC}"
    echo ""
}

# Main
cd "$(dirname "$0")"

# Parse arguments
NO_RESET=false
TASK_ID=""
MODEL_ARG=""

for arg in "$@"; do
    case $arg in
        --no-reset)
            NO_RESET=true
            ;;
        list|--list|-l)
            list_tasks
            exit 0
            ;;
        task*)
            TASK_ID="$arg"
            ;;
        *)
            MODEL_ARG="$arg"
            ;;
    esac
done

if [ -n "$MODEL_ARG" ]; then
    MODEL="$MODEL_ARG"
fi

check_api_key

# Reset database before running (unless --no-reset)
if [ "$NO_RESET" = false ]; then
    reset_database
fi

if [ -z "$TASK_ID" ]; then
    echo -e "${YELLOW}Running all tasks...${NC}"
    echo ""
    for task in task1 task2 task3 task4 task5 task6; do
        run_task "$task"
        # Reset between tasks
        if [ "$NO_RESET" = false ]; then
            reset_database
        fi
    done
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}All tasks completed!${NC}"
    echo -e "${GREEN}Results saved in: research/experiments/runs/${NC}"
    echo -e "${GREEN}========================================${NC}"
else
    run_task "$TASK_ID"
fi
