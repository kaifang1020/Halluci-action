#!/usr/bin/env bash
# Sweep runner for the v2 benchmark (post time-change). Wraps
# scripts/run_experiments_v1.py over the (agent, model, kl) combinations
# defined in experiments/sweeps/v2.yaml. Defaults to HPC runtime (no docker);
# override HALLUCI_RUNTIME=docker for local docker-compose runs.
#
# Usage:
#   ./run_experiment_v2.sh                                          # full sweep
#   DRY_RUN=1 ./run_experiment_v2.sh                                # print plan
#   SKIP_EXISTING=1 ./run_experiment_v2.sh                          # resume
#   SWEEP_CONFIG=experiments/sweeps/quick.yaml ./run_experiment_v2.sh
#   RUNS=3 MAX_STEPS=20 ./run_experiment_v2.sh
#   HALLUCI_RUNTIME=docker ./run_experiment_v2.sh
#   nohup ./run_experiment_v2.sh > logs/v2_master.log 2>&1 &

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

# --- defaults (overridable via env or research/.env) -------------------------
: "${HALLUCI_RUNTIME:=hpc}"
: "${BENCHMARK_CURRENT_DATE:=2026-05-08}"
: "${BENCHMARK_CURRENT_TIME:=09:00:00}"
: "${BENCHMARK_TIMEZONE:=Asia/Shanghai}"
: "${RUNS:=1}"
: "${MAX_STEPS:=15}"
: "${CONDA_ENV_NAME:=odoo-research}"
: "${SWEEP_CONFIG:=$ROOT_DIR/experiments/sweeps/v2.yaml}"
export HALLUCI_RUNTIME BENCHMARK_CURRENT_DATE BENCHMARK_CURRENT_TIME BENCHMARK_TIMEZONE

LOCAL_NO_PROXY="localhost,127.0.0.1,::1"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}$LOCAL_NO_PROXY"
export no_proxy="${no_proxy:+$no_proxy,}$LOCAL_NO_PROXY"

# Load research/.env (API keys, ODOO_DB, DATA_ROOT, ...)
if [[ -f "$ROOT_DIR/research/.env" ]]; then
  set -a; source "$ROOT_DIR/research/.env"; set +a
fi

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

die() { echo -e "${RED}ERROR:${NC} $*" >&2; exit 1; }
warn() { echo -e "${YELLOW}WARN:${NC} $*" >&2; }
ok() { echo -e "${GREEN}$*${NC}"; }

# --- preflight ---------------------------------------------------------------
command -v conda >/dev/null || die "conda not on PATH"
conda env list | awk '{print $1}' | grep -qx "$CONDA_ENV_NAME" \
  || die "conda env '$CONDA_ENV_NAME' not found"
conda run -n "$CONDA_ENV_NAME" python -c 'import research.harness, yaml' 2>/dev/null \
  || die "conda env '$CONDA_ENV_NAME' missing research.harness or PyYAML (try: conda run -n $CONDA_ENV_NAME pip install pyyaml)"
[[ -f "$SWEEP_CONFIG" ]] || die "sweep config not found: $SWEEP_CONFIG"

if [[ "$HALLUCI_RUNTIME" == "hpc" ]]; then
  CONDA_ENV_PATH="$(conda env list | awk -v n="$CONDA_ENV_NAME" '$1==n{print $NF}')"
  [[ -x "$CONDA_ENV_PATH/bin/odoo"   ]] || die "odoo binary not in $CONDA_ENV_NAME ($CONDA_ENV_PATH/bin/odoo)"
  [[ -x "$CONDA_ENV_PATH/bin/pg_ctl" ]] || die "pg_ctl not in $CONDA_ENV_NAME ($CONDA_ENV_PATH/bin/pg_ctl)"
  DATA_ROOT_EFFECTIVE="${DATA_ROOT:-/gpfsnyu/scratch/km6704/odoo-research}"
  if [[ "$DATA_ROOT_EFFECTIVE" == */km6704/* && "${USER:-}" != "km6704" ]]; then
    warn "DATA_ROOT='$DATA_ROOT_EFFECTIVE' points at km6704's scratch but USER=$USER."
    warn "Set DATA_ROOT=/gpfsnyu/scratch/\$USER/odoo-research in research/.env to use your own scratch."
  fi
elif [[ "$HALLUCI_RUNTIME" == "docker" ]]; then
  command -v docker >/dev/null || die "HALLUCI_RUNTIME=docker but docker not on PATH"
  docker info >/dev/null 2>&1 || die "HALLUCI_RUNTIME=docker but cannot access docker daemon"
else
  die "Unsupported HALLUCI_RUNTIME='$HALLUCI_RUNTIME' (expected docker or hpc)"
fi

# Preview sweep (also serves as a YAML sanity check)
mapfile -t SWEEP < <(conda run -n "$CONDA_ENV_NAME" --no-capture-output \
  python "$ROOT_DIR/scripts/sweep_pairs.py" "$SWEEP_CONFIG")
[[ ${#SWEEP[@]} -gt 0 ]] || die "sweep config produced no (agent, model, kl) rows"

# Per-provider API key check before any long run.
declare -A PROVIDER_KEY=(
  [anthropic]=ANTHROPIC_API_KEY
  [claude]=ANTHROPIC_API_KEY
  [openai]=OPENAI_API_KEY
  [deepseek]=DEEPSEEK_API_KEY
  [gemini]=GOOGLE_API_KEY
  [qwen]=DASHSCOPE_API_KEY
  [kimi]=MOONSHOT_API_KEY
)
declare -A CHECKED_KEYS=()
for row in "${SWEEP[@]}"; do
  IFS=$'\t' read -r AGENT _MODEL _KL <<< "$row"
  key_var="${PROVIDER_KEY[$AGENT]:-}"
  [[ -n "$key_var" ]] || die "unknown provider '$AGENT' in sweep config"
  [[ -z "${CHECKED_KEYS[$key_var]:-}" ]] || continue
  [[ -n "${!key_var:-}" ]] || die "missing $key_var (required by provider '$AGENT'); set it in research/.env"
  CHECKED_KEYS[$key_var]=1
done

# --- plan banner -------------------------------------------------------------
TS="$(date -u +%Y%m%dT%H%M%SZ)"
START_TS="$TS"
[[ "${DRY_RUN:-0}" == "1" ]] || mkdir -p logs

echo
echo "============================================================"
echo "  Halluci-Action v2 benchmark sweep"
echo "============================================================"
echo "  Sweep config: $SWEEP_CONFIG"
echo "  Runtime:      $HALLUCI_RUNTIME"
echo "  Benchmark:    ${BENCHMARK_CURRENT_DATE}T${BENCHMARK_CURRENT_TIME} ${BENCHMARK_TIMEZONE}"
echo "  Runs/task:    $RUNS    Max steps: $MAX_STEPS"
echo "  Started:      $TS"
echo "  Pairs:"
printf '    - %s\n' "${SWEEP[@]}"
echo "============================================================"

EXIT_SUMMARY=()

# --- main loop ---------------------------------------------------------------
for row in "${SWEEP[@]}"; do
  IFS=$'\t' read -r AGENT MODEL KL <<< "$row"
  LOG="logs/run_v2_${AGENT}_${MODEL}_${TS}.log"
  echo
  echo "------------------------------------------------------------"
  echo "  Sweep step: $AGENT / $MODEL  (kl=$KL)"
  echo "  Log:        $LOG"
  echo "------------------------------------------------------------"

  EXTRA=()
  [[ "${SKIP_EXISTING:-0}" == "1" ]] && EXTRA+=(--skip-existing)
  [[ "${DRY_RUN:-0}"       == "1" ]] && EXTRA+=(--dry-run)

  STEP_OK=0
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    conda run -n "$CONDA_ENV_NAME" --no-capture-output \
      python scripts/run_experiments_v1.py \
        --mode all --agent "$AGENT" --model "$MODEL" --kl "$KL" \
        --runs "$RUNS" --max-steps "$MAX_STEPS" "${EXTRA[@]}" \
      && STEP_OK=1 || STEP_OK=0
  else
    conda run -n "$CONDA_ENV_NAME" --no-capture-output \
      python scripts/run_experiments_v1.py \
        --mode all --agent "$AGENT" --model "$MODEL" --kl "$KL" \
        --runs "$RUNS" --max-steps "$MAX_STEPS" "${EXTRA[@]}" \
      2>&1 | tee "$LOG"
    # PIPESTATUS[0] is the python exit code (tee always succeeds).
    [[ "${PIPESTATUS[0]}" -eq 0 ]] && STEP_OK=1 || STEP_OK=0
  fi

  if [[ "$STEP_OK" -eq 1 ]]; then
    EXIT_SUMMARY+=("OK     $AGENT/$MODEL  log=$LOG")
    ok "Sweep step OK: $AGENT/$MODEL"
  else
    EXIT_SUMMARY+=("FAIL   $AGENT/$MODEL  log=$LOG")
    warn "Sweep step FAILED: $AGENT/$MODEL — continuing to next pair to preserve partial results."
  fi
done

# --- finalize ---------------------------------------------------------------
echo
echo "============================================================"
echo "  Sweep complete. Per-step status:"
echo "============================================================"
printf '  %s\n' "${EXIT_SUMMARY[@]}"

if [[ "${DRY_RUN:-0}" != "1" ]]; then
  REPORT="logs/sweep_summary_${START_TS}.md"
  echo
  echo "Aggregating summaries into $REPORT ..."
  conda run -n "$CONDA_ENV_NAME" --no-capture-output \
    python "$ROOT_DIR/scripts/summarize_sweep.py" \
      --since "$START_TS" \
      --out "$REPORT" \
    || warn "summarize_sweep.py exited non-zero; raw jsonls in research/experiments_v1/run_summaries/"
  ok "Report: $REPORT"
fi
