#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="$ROOT_DIR/research/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

LOCAL_NO_PROXY="localhost,127.0.0.1,::1"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}$LOCAL_NO_PROXY"
export no_proxy="${no_proxy:+$no_proxy,}$LOCAL_NO_PROXY"

RUNTIME="${HALLUCI_RUNTIME:-docker}"
case "$RUNTIME" in
  docker)
    RESET_SCRIPT="$ROOT_DIR/scripts/reset.sh"
    if ! command -v docker >/dev/null 2>&1; then
      echo "ERROR: docker is not available on PATH; cannot reset/furnish the Odoo database." >&2
      exit 127
    fi
    if ! docker info >/dev/null 2>&1; then
      echo "ERROR: docker is installed but this session cannot access the Docker daemon." >&2
      echo "       Fix Docker socket permissions or run on a node/session where docker compose works." >&2
      exit 126
    fi
    ;;
  hpc)
    RESET_SCRIPT="$ROOT_DIR/scripts/reset_hpc.sh"
    ;;
  *)
    echo "ERROR: unsupported HALLUCI_RUNTIME='$RUNTIME' (expected docker or hpc)." >&2
    exit 2
    ;;
esac

if ! command -v conda >/dev/null 2>&1; then
  echo "ERROR: conda is not available on PATH; cannot run the odoo-research environment." >&2
  exit 127
fi
if ! conda run -n odoo-research python3 -c 'import structlog; import research.harness' >/dev/null 2>&1; then
  echo "ERROR: conda env 'odoo-research' is missing required Python dependencies." >&2
  echo "       Activate/fix that env, then retry." >&2
  exit 126
fi

STAMP="${1:-$(date -u +%Y%m%dT%H%M%SZ)}"
OUT_ROOT="$ROOT_DIR/research/experiments/dependent_remaining_${STAMP}"
RUNS_DIR="$ROOT_DIR/research/experiments/runs"
CHAIN_FILTER="${CHAIN_FILTER:-}"
mkdir -p "$OUT_ROOT/logs"

CHAINS=(
  "A2_A6:A-2 A-6"
  "C1_C5:C-1 C-5"
  "PU2_PU4:PU-2 PU-4"
  "PU3_PU5:PU-3 PU-5"
  "C2_P2:C-2 P-2"
  "P1_P4:P-1 P-4"
  "P3:P-3"
  "P5:P-5"
  "P6:P-6"
  "M1_M2:M-1 M-2"
  "M3_M4:M-3 M-4"
  "M1_M5:M-1 M-2 M-3 M-4 M-5"
  "M1_M6:M-1 M-2 M-3 M-4 M-5 M-6"
  "PR1_PR4:PR-1 PR-4"
  "PR1_PR6:PR-1 PR-2 PR-3 PR-4 PR-5 PR-6"
)

domain_for_task() {
  case "$1" in
    S-*)  printf "sales" ;;
    I-*)  printf "inventory" ;;
    A-*)  printf "accounting" ;;
    C-*)  printf "crm" ;;
    P-*)  printf "pos" ;;
    H-*)  printf "hr" ;;
    D-*)  printf "helpdesk" ;;
    PU-*) printf "purchase" ;;
    M-*)  printf "manufacturing" ;;
    PR-*) printf "project" ;;
    *)    printf "unknown" ;;
  esac
}

status_file="$OUT_ROOT/status.tsv"
if [[ ! -s "$status_file" ]]; then
  printf "timestamp\tchain\ttask\tdomain\tstatus\ttrajectory\n" > "$status_file"
fi

echo "Dependent remaining chains started at $(date -Is)"
echo "Output root: $OUT_ROOT"
echo "Runtime: $RUNTIME"
if [[ -n "$CHAIN_FILTER" ]]; then
  echo "Chain filter: $CHAIN_FILTER"
fi

for chain_spec in "${CHAINS[@]}"; do
  chain_name="${chain_spec%%:*}"
  task_list="${chain_spec#*:}"
  if [[ -n "$CHAIN_FILTER" && "$chain_name" != "$CHAIN_FILTER" ]]; then
    continue
  fi

  chain_dir="$OUT_ROOT/chains/$chain_name"
  chain_log="$chain_dir/run.log"
  mkdir -p "$chain_dir"

  echo
  echo "===== [$chain_name] reset + furnish + run: $task_list ====="
  {
    echo "[$(date -Is)] reset"
    bash "$RESET_SCRIPT"

    echo "[$(date -Is)] furnish"
    conda run -n odoo-research --no-capture-output \
      python3 "$ROOT_DIR/scripts/furnish_database.py"
  } >"$chain_log" 2>&1

  for task_id in $task_list; do
    domain="$(domain_for_task "$task_id")"
    task_dir="$chain_dir/$domain/$task_id"
    task_log="$task_dir/run.log"
    mkdir -p "$task_dir"

    echo "----- [$chain_name/$task_id] run -----"
    marker="$(mktemp /tmp/halluci_action_marker_${chain_name}_${task_id//-/_}.XXXXXX)"
    touch "$marker"
    status="success"
    trajectory=""

    {
      echo "[$(date -Is)] run $task_id"
      if ! "$ROOT_DIR/run_experiment_codex.sh" "$task_id"; then
        echo "ERROR: run failed for $task_id" >&2
        status="failed"
      fi
    } >"$task_log" 2>&1

    if [[ "$status" == "success" ]]; then
      trajectory="$(
        find "$RUNS_DIR" -maxdepth 1 -type f -name '*.json' -newer "$marker" -printf '%T@ %p\n' \
          | sort -nr \
          | awk 'NR==1 {print $2}'
      )"
      if [[ -n "$trajectory" && -f "$trajectory" ]]; then
        cp "$trajectory" "$task_dir/"
        echo "Saved trajectory copy: $task_dir/$(basename "$trajectory")"
      else
        status="missing_trajectory"
        echo "WARNING: no trajectory JSON found for $task_id after marker $marker" | tee -a "$task_log"
      fi
    fi

    rm -f "$marker"
    printf "%s\t%s\t%s\t%s\t%s\t%s\n" "$(date -Is)" "$chain_name" "$task_id" "$domain" "$status" "$trajectory" >> "$status_file"
    echo "[$chain_name/$task_id] status=$status"
  done
done

echo
echo "Dependent remaining chains finished at $(date -Is)"
echo "Status file: $status_file"
