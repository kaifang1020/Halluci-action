#!/usr/bin/env bash
#SBATCH --job-name=halluci-eval
#SBATCH --time=24:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=1
#SBATCH --output=research/experiments/slurm-%x-%j.out
#SBATCH --error=research/experiments/slurm-%x-%j.err

set -euo pipefail

ROOT_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT_DIR"

EXP_DIR="${1:-$ROOT_DIR/research/experiments/independent_non_p_m_pr_20260427T074902Z}"

echo "Job started: $(date -Is)"
echo "Host: $(hostname)"
echo "Root: $ROOT_DIR"
echo "Experiment dir: $EXP_DIR"
echo "Eval profile: ${EVAL_PROFILE:-from env file}"

bash "$ROOT_DIR/scripts/run_eval_directory.sh" "$EXP_DIR"

echo "Job finished: $(date -Is)"
