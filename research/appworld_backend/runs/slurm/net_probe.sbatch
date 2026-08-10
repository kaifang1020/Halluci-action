#!/bin/bash
#SBATCH --job-name=aw_net_probe
#SBATCH --partition=cpu_short
#SBATCH --account=torch_pr_1017_general
#SBATCH --time=00:05:00
#SBATCH --mem=2G
#SBATCH --cpus-per-task=2
#SBATCH --output=/scratch/cl7990/Halluci-action/research/appworld_backend/runs/slurm/net_probe.out
echo "node=$(hostname)"; env | grep -i proxy || echo "no proxy vars"
for u in https://ai-gateway.apps.cloud.rt.nyu.edu/v1/models https://api.deepseek.com/v1/models https://dashscope.aliyuncs.com/compatible-mode/v1/models https://api.openai.com/v1/models; do
  code=$(curl -sS -o /dev/null -m 20 -w "%{http_code}" "$u" 2>&1 | tail -c 40)
  echo "PROBE $u -> $code"
done
