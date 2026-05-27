#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="$ROOT_DIR/research/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

LOCAL_NO_PROXY="localhost,127.0.0.1,::1"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}$LOCAL_NO_PROXY"
export no_proxy="${no_proxy:+$no_proxy,}$LOCAL_NO_PROXY"

TASKS=(
    S-1 S-2 S-3 S-4 S-5 S-6
    I-1 I-2 I-3 I-4 I-5 I-6
    A-1 A-2 A-3 A-4 A-5 A-6
    C-1 C-2 C-3 C-4 C-5 C-6
    P-1 P-2 P-3 P-4 P-5 P-6
    H-1 H-2 H-3 H-4 H-5 H-6
    D-1 D-2 D-3 D-4 D-5 D-6
    PU-1 PU-2 PU-3 PU-4 PU-5 PU-6
    M-1 M-2 M-3 M-4 M-5 M-6
    PR-1 PR-2 PR-3 PR-4 PR-5 PR-6
)

"${PYTHON:-python3}" scripts/run_experiments_v1.py \
    --mode independent \
    --tasks "${TASKS[@]}" \
    --agent "${DEFAULT_AGENT:-deepseek}" \
    --model "${DEFAULT_MODEL:-deepseek-chat}" \
    --experiments-dir research/experiments_v2/real \
    --timeout-sec "${TIMEOUT_SEC:-600}" \
    "$@"
