#!/bin/bash
#SBATCH --job-name=aw_batchC_judge
#SBATCH --partition=cpu_short
#SBATCH --account=torch_pr_1017_general
#SBATCH --time=06:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=5
#SBATCH --output=/scratch/cl7990/Halluci-action/research/appworld_backend/runs/slurm/batch_C_teammate_judge_%j.out

# Stage-2 judge for Batch C-teammate, judging whatever trajectories exist.
# Single process, 4 workers — the validated single-key ceiling. judge_all.py
# skips every cell whose pipeline_<task>_<tag>.html already exists, so chained
# resubmits of this job simply continue where the previous one stopped.
set -uo pipefail
repo=/scratch/cl7990/Halluci-action
cd "$repo"
sha256sum --check research/judge_versions/appworld_experiment_old_judge_20260802/SHA256SUMS
tasks=$("$repo/research/.venv/bin/python" -c 'import json;print(",".join(json.load(open("research/appworld_backend/tasks/batch_C_teammate.json"))))')
echo "job=$SLURM_JOB_ID node=$(hostname) started=$(date --iso-8601=seconds)"
env APPWORLD_ROOT="$repo/.appworld-root" \
    APPWORLD_CACHE="$repo/.appworld-root/.cache" \
    PYTHONPATH="$repo" \
  "$repo/research/.venv/bin/python" research/appworld_backend/judge_all.py \
    --tasks "$tasks" \
    --judge gemini-pro \
    --workers 4 \
    --timeout 3600 \
    --retries 3 \
  >> "$repo/research/appworld_backend/runs/batch_C_teammate_stage2.log" 2>&1
rc=$?
echo "judge exit=$rc finished=$(date --iso-8601=seconds)"
exit $rc
