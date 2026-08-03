#!/bin/bash
# Launch the Batch C-teammate stage-2 judge detached on the current node.
# Run this INSIDE a compute-node allocation; it survives ssh disconnect but
# ends with the Slurm job. judge_all.py is resumable, so relaunching later
# only judges cells whose pipeline_<task>_<tag>.html does not yet exist.
set -euo pipefail
repo=/scratch/cl7990/Halluci-action
cd "$repo"
if pgrep -u "$USER" -f 'judge_all\.py --tasks' >/dev/null; then
  echo "refusing: a judge_all.py is already running for this user" >&2
  exit 3
fi
tasks=$("$repo/research/.venv/bin/python" -c 'import json;print(",".join(json.load(open("research/appworld_backend/tasks/batch_C_teammate.json"))))')
setsid nohup env \
  APPWORLD_ROOT="$repo/.appworld-root" \
  APPWORLD_CACHE="$repo/.appworld-root/.cache" \
  PYTHONPATH="$repo" \
  "$repo/research/.venv/bin/python" research/appworld_backend/judge_all.py \
    --tasks "$tasks" \
    --judge gemini-pro \
    --workers 4 \
    --timeout 3600 \
    --retries 3 \
  >> "$repo/research/appworld_backend/runs/batch_C_teammate_stage2.log" 2>&1 &
echo "launched judge_all pid=$! on $(hostname)"
