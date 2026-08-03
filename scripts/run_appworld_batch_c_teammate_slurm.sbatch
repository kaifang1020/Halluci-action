#!/bin/bash
#SBATCH --job-name=aw_batchC_tm
#SBATCH --partition=cpu_short
#SBATCH --account=torch_pr_1017_general
#SBATCH --time=48:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=4
#SBATCH --output=/scratch/cl7990/Halluci-action/research/appworld_backend/runs/slurm/batch_C_teammate_%j.out

# Slurm wrapper for the Batch C-teammate AppWorld pipeline (stage 1 -> stage 2).
# The login-node user slice has a 3 GiB memory.max that OOM-killed every
# previous attempt; a compute-node allocation sidesteps that limit entirely.
# Both stages are resumable, so a timeout or preemption just needs a resubmit.
set -uo pipefail
cd /scratch/cl7990/Halluci-action
echo "job=$SLURM_JOB_ID node=$(hostname) started=$(date --iso-8601=seconds)"
scripts/run_appworld_batch_c_teammate_pipeline.sh
rc=$?
echo "pipeline exit=$rc finished=$(date --iso-8601=seconds)"
exit $rc
