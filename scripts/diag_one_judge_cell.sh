#!/bin/bash
# Reproduce a single stage-2 judge cell in the foreground for diagnosis.
set -uo pipefail
repo=/scratch/cl7990/Halluci-action
cd "$repo"
env APPWORLD_ROOT="$repo/.appworld-root" \
    APPWORLD_CACHE="$repo/.appworld-root/.cache" \
    PYTHONPATH="$repo" \
  "$repo/research/.venv/bin/python" research/appworld_backend/run_pipeline.py \
    --task-id 07b42fd_2 \
    --traj research/appworld_backend/runs/trajectories/07B42FD-2_gemini_vertexai_hs3645_gemini_3_flash_preview.json \
    --tag gemflash \
    --judge gemini-pro \
    --provider gemini \
    --model '@vertexai-hs3645/gemini-3-flash-preview'
