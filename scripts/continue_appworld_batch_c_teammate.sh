#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 STAGE1_PID" >&2
  exit 2
fi

stage1_pid="$1"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
stage1_log="$repo_root/research/appworld_backend/runs/batch_C_teammate_stage1.log"
continuation_log="$repo_root/research/appworld_backend/runs/batch_C_teammate_continuation.log"

exec >>"$continuation_log" 2>&1
echo "Waiting for Stage 1 PID $stage1_pid"
while kill -0 "$stage1_pid" 2>/dev/null; do
  sleep 30
done

if ! grep -q '^=== TRAJECTORIES ===' "$stage1_log"; then
  echo "Stage 1 exited without a final summary; Stage 2 will not start."
  exit 4
fi

echo "Stage 1 finished; starting Stage 2."
exec "$repo_root/scripts/run_appworld_batch_c_teammate_stage2.sh"
