#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="$repo_root/research/.venv/bin/python"
task_file="$repo_root/research/appworld_backend/tasks/batch_C_teammate.json"
log_file="$repo_root/research/appworld_backend/runs/batch_C_teammate_stage1.log"

task_csv="$($python_bin -c 'import json, sys; print(",".join(json.load(open(sys.argv[1]))))' "$task_file")"

export APPWORLD_ROOT="${APPWORLD_ROOT:-$repo_root/.appworld-root}"
export APPWORLD_CACHE="${APPWORLD_CACHE:-$APPWORLD_ROOT/.cache}"
export PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}"

cd "$repo_root"
exec > >(tee -a "$log_file") 2>&1
exec "$python_bin" research/appworld_backend/gen_trajectories.py \
  --tasks "$task_csv" \
  --max-steps 40
