#!/usr/bin/env bash
#SBATCH --job-name=halluci-nonpmpr
#SBATCH --time=04:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=1
#SBATCH --output=research/experiments/slurm-%x-%j.out
#SBATCH --error=research/experiments/slurm-%x-%j.err

set -euo pipefail

ROOT_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT_DIR"

mkdir -p research/experiments

if [[ -f "$HOME/.bashrc" ]]; then
  # Make conda/module setup from interactive shells available in sbatch.
  # shellcheck source=/dev/null
  set +u
  source "$HOME/.bashrc"
  set -u
fi

STAMP="${1:-$(date -u +%Y%m%dT%H%M%SZ)}"
START_FROM="${2:-${START_TASK:-}}"

export HALLUCI_RUNTIME="${HALLUCI_RUNTIME:-hpc}"

echo "Job started: $(date -Is)"
echo "Host: $(hostname)"
echo "Root: $ROOT_DIR"
echo "Stamp: $STAMP"
echo "Runtime: $HALLUCI_RUNTIME"
if [[ -n "$START_FROM" ]]; then
  echo "Start task: $START_FROM"
  export START_TASK="$START_FROM"
fi

bash "$ROOT_DIR/scripts/run_independent_non_p_m_pr.sh" "$STAMP"

echo "Job finished: $(date -Is)"
