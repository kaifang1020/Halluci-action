#!/usr/bin/env bash
# =============================================================================
# run_eval.sh — Halluci-Action evaluation pipeline entry point
#
# Runs the 4-pass evaluation on a trajectory JSON produced by run_experiment_codex.sh.
#
# Usage:
#   ./run_eval.sh <trajectory.json>
#   ./run_eval.sh <trajectory.json> --profile deepseek
#   ./run_eval.sh <trajectory.json> --profile gemini-pro
#   ./run_eval.sh <trajectory.json> --keep-intermediate
#   ./run_eval.sh <trajectory.json> --heuristic
#   ./run_eval.sh <trajectory.json> --gaps-only
#
# Default judge profile: openai (gpt-4o)
# Output: <trajectory_dir>/evaluations/results/<stem>__final.json
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/research/.env"
EVAL_SCRIPT="$SCRIPT_DIR/research/eval/run_pipeline.py"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found."
    exit 1
fi
set -a
source "$ENV_FILE"
set +a

TRAJ="${1:-}"
if [[ -z "$TRAJ" ]]; then
    echo "Usage: $0 <trajectory.json> [options]"
    echo
    echo "Options are passed through to run_pipeline.py:"
    echo "  --profile <openai|deepseek|gemini-pro|gemini-flash>"
    echo "  --keep-intermediate"
    echo "  --heuristic"
    echo "  --gaps-only"
    echo "  --pass1-existing <pass1.json>"
    echo "  --model-1a <model>  --model-1b <model>  --model-stage1 <model>  --model-stage2 <model>"
    exit 1
fi
shift

conda run -n odoo-research --no-capture-output \
    python3 "$EVAL_SCRIPT" \
        --trajectory "$TRAJ" \
        --env-file "$ENV_FILE" \
        "$@"
