#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${EVAL_ENV_FILE:-$ROOT_DIR/research/.env}"
EXP_DIR="${1:-$ROOT_DIR/research/experiments/independent_non_p_m_pr_20260427T074902Z}"
PROFILE="${EVAL_PROFILE:-}"
EXTRA_ARGS="${EVAL_EXTRA_ARGS:-}"

if [[ ! -d "$EXP_DIR" ]]; then
  echo "ERROR: experiment directory not found: $EXP_DIR" >&2
  exit 2
fi

if [[ -f "$HOME/.bashrc" ]]; then
  # Make conda/module setup from interactive shells available on HPC.
  # shellcheck source=/dev/null
  set +u
  source "$HOME/.bashrc"
  set -u
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "ERROR: conda is not available on PATH." >&2
  exit 127
fi

if ! conda run -n odoo-research python3 -c 'import click, openai' >/dev/null 2>&1; then
  echo "ERROR: conda env 'odoo-research' is missing evaluation dependencies." >&2
  exit 126
fi

OUT_DIR="${EVAL_OUTPUT_DIR:-$EXP_DIR/evaluations/results}"
DEBUG_DIR="${EVAL_DEBUG_DIR:-$EXP_DIR/evaluations/debug}"
LOG_DIR="${EVAL_LOG_DIR:-$EXP_DIR/evaluations/logs}"
STATUS_FILE="${EVAL_STATUS_FILE:-$EXP_DIR/evaluations/status.tsv}"
mkdir -p "$OUT_DIR" "$DEBUG_DIR" "$LOG_DIR"

if [[ ! -s "$STATUS_FILE" ]]; then
  printf "timestamp\tstatus\ttrajectory\tresult\tlog\n" > "$STATUS_FILE"
fi

mapfile -t TRAJECTORIES < <(
  find "$EXP_DIR" -mindepth 3 -maxdepth 3 -type f -name '*.json' \
    ! -path '*/evaluations/*' \
    | sort
)

echo "Evaluation batch started at $(date -Is)"
echo "Experiment dir: $EXP_DIR"
echo "Trajectories: ${#TRAJECTORIES[@]}"
echo "Output dir: $OUT_DIR"
echo "Env file: $ENV_FILE"
if [[ -n "$PROFILE" ]]; then
  echo "Profile override: $PROFILE"
fi
if [[ -n "$EXTRA_ARGS" ]]; then
  echo "Extra args: $EXTRA_ARGS"
fi

for trajectory in "${TRAJECTORIES[@]}"; do
  stem="$(basename "$trajectory" .json)"
  result="$OUT_DIR/${stem}__final.json"
  log="$LOG_DIR/${stem}.log"

  if [[ -s "$result" && "${EVAL_FORCE:-0}" != "1" ]]; then
    echo "SKIP existing: $trajectory"
    printf "%s\tskipped\t%s\t%s\t%s\n" "$(date -Is)" "$trajectory" "$result" "$log" >> "$STATUS_FILE"
    continue
  fi

  echo
  echo "===== evaluate: $trajectory ====="
  status="success"
  cmd=(
    conda run -n odoo-research --no-capture-output
    python3 "$ROOT_DIR/research/eval/run_pipeline.py"
    --trajectory "$trajectory"
    --output-dir "$OUT_DIR"
    --work-dir "$DEBUG_DIR/$stem"
    --env-file "$ENV_FILE"
  )
  if [[ -n "$PROFILE" ]]; then
    cmd+=(--profile "$PROFILE")
  fi
  if [[ "${EVAL_KEEP_INTERMEDIATE:-0}" == "1" ]]; then
    cmd+=(--keep-intermediate)
  fi
  if [[ "${EVAL_GAPS_ONLY:-0}" == "1" ]]; then
    cmd+=(--gaps-only)
  fi
  if [[ "${EVAL_HEURISTIC:-0}" == "1" ]]; then
    cmd+=(--heuristic)
  fi
  if [[ -n "$EXTRA_ARGS" ]]; then
    # shellcheck disable=SC2206
    extra_words=($EXTRA_ARGS)
    cmd+=("${extra_words[@]}")
  fi

  if ! "${cmd[@]}" >"$log" 2>&1; then
    status="failed"
    echo "ERROR: evaluation failed for $trajectory; see $log" >&2
  fi

  if [[ "$status" == "success" && ! -s "$result" ]]; then
    status="missing_result"
    echo "ERROR: expected result missing for $trajectory: $result" >&2
  fi

  printf "%s\t%s\t%s\t%s\t%s\n" "$(date -Is)" "$status" "$trajectory" "$result" "$log" >> "$STATUS_FILE"
  echo "status=$status result=$result"
done

echo
echo "Evaluation batch finished at $(date -Is)"
echo "Status file: $STATUS_FILE"
