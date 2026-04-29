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
OUT_ROOT="$ROOT_DIR/research/experiments/independent_non_p_m_pr_${STAMP}"
RUNS_DIR="$ROOT_DIR/research/experiments/runs"
mkdir -p "$OUT_ROOT/logs"
START_TASK="${START_TASK:-}"

TASKS=(
  S-1 S-2 S-3 S-4 S-5 S-6
  I-1 I-2 I-3 I-4 I-5 I-6
  A-1 A-2 A-3 A-4 A-5 A-6
  C-1 C-2 C-3 C-4 C-5 C-6
  H-1 H-2 H-3 H-4 H-5 H-6
  D-1 D-2 D-3 D-4 D-5 D-6
  PU-1 PU-2 PU-3 PU-4 PU-5 PU-6
)

domain_for_task() {
  case "$1" in
    S-*)  printf "sales" ;;
    I-*)  printf "inventory" ;;
    A-*)  printf "accounting" ;;
    C-*)  printf "crm" ;;
    H-*)  printf "hr" ;;
    D-*)  printf "helpdesk" ;;
    PU-*) printf "purchase" ;;
    *)    printf "unknown" ;;
  esac
}

status_file="$OUT_ROOT/status.tsv"
if [[ ! -s "$status_file" ]]; then
  printf "timestamp\ttask\tdomain\tstatus\ttrajectory\n" > "$status_file"
fi

echo "Independent non-P/M/PR scan started at $(date -Is)"
echo "Output root: $OUT_ROOT"
echo "Runtime: $RUNTIME"
echo "Tasks: ${#TASKS[@]}"
if [[ -n "$START_TASK" ]]; then
  echo "Start task: $START_TASK"
fi

started=false
if [[ -z "$START_TASK" ]]; then
  started=true
fi

for task_id in "${TASKS[@]}"; do
  if [[ "$started" == false ]]; then
    if [[ "$task_id" == "$START_TASK" ]]; then
      started=true
    else
      continue
    fi
  fi

  domain="$(domain_for_task "$task_id")"
  task_dir="$OUT_ROOT/$domain/$task_id"
  task_log="$task_dir/run.log"
  mkdir -p "$task_dir"

  echo
  echo "===== [$task_id] $domain | reset + furnish + run ====="
  marker="$(mktemp /tmp/halluci_action_marker_${task_id//-/_}.XXXXXX)"
  touch "$marker"

  status="success"
  trajectory=""
  {
    echo "[$(date -Is)] reset"
    if ! bash "$RESET_SCRIPT"; then
      echo "ERROR: reset failed for $task_id" >&2
      status="failed"
    fi

    if [[ "$status" == "success" ]]; then
      echo "[$(date -Is)] furnish"
      if ! conda run -n odoo-research --no-capture-output \
        python3 "$ROOT_DIR/scripts/furnish_database.py"; then
        echo "ERROR: furnish failed for $task_id" >&2
        status="failed"
      fi
    fi

    if [[ "$status" == "success" ]]; then
      echo "[$(date -Is)] run $task_id"
      if ! "$ROOT_DIR/run_experiment_codex.sh" "$task_id"; then
        echo "ERROR: run failed for $task_id" >&2
        status="failed"
      fi
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
  printf "%s\t%s\t%s\t%s\t%s\n" "$(date -Is)" "$task_id" "$domain" "$status" "$trajectory" >> "$status_file"
  echo "[$task_id] status=$status"
done

echo
echo "Independent non-P/M/PR scan finished at $(date -Is)"
echo "Status file: $status_file"
