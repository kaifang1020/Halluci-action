#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_dir="$repo_root/research/appworld_backend/runs"
pipeline_log="$run_dir/batch_C_teammate_pipeline.log"
lock_file="$run_dir/batch_C_teammate_pipeline.lock"

mkdir -p "$run_dir"
exec 9>"$lock_file"
if ! flock -n 9; then
  echo "Refusing to start: the batch C teammate pipeline is already active." >&2
  exit 3
fi

exec >>"$pipeline_log" 2>&1
echo "[$(date --iso-8601=seconds)] pipeline start/resume"

echo "[$(date --iso-8601=seconds)] starting Stage 1"
"$repo_root/scripts/run_appworld_batch_c_teammate_stage1.sh"
echo "[$(date --iso-8601=seconds)] Stage 1 process completed"

# The Stage 2 launcher independently verifies the frozen old-judge hashes and
# the full 111 x 5 trajectory matrix before it starts any judge workers.
echo "[$(date --iso-8601=seconds)] starting Stage 2"
"$repo_root/scripts/run_appworld_batch_c_teammate_stage2.sh"
echo "[$(date --iso-8601=seconds)] pipeline completed"
