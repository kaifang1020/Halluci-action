#!/usr/bin/env bash
#
# Run the Stage 2 *v2* judge over both trajectory authors:
#   deepseek-chat -> stage1 in eval_v3-1_claim2action/stage1/results_deepseek_chat
#                    trajectories experiments_v2/real/{independent,dependent}
#   gpt-4o        -> stage1 in eval_v3/stage1/results_gpt4o
#                    trajectories experiments_v2/{independent,dependent} (top-level)
#
# Scope: Stage 2 only (preprocess -> render -> judge) at --prompt-version v2.
# Stage 1 is NOT re-run. Judge = deepseek-v4-pro (gemini Portkey key is dead;
# v1 baselines were gemini, so v1->v2 deltas mix judges — see CHANGELOG.md).
#
# Outputs (v1 dirs left intact; the v2 suffix is appended by --prompt-version):
#   binary_results_deepseek_chat_v2/{independent,dependent}/
#   binary_results_gpt4o_v2/{independent,dependent}/
#
# run_stage2.py is invoked as a SCRIPT (this package's dir has a hyphen and is
# not importable); it bootstraps sys.path itself. Resumable: existing v2
# verdict files are skipped (no --overwrite).
set -uo pipefail

cd "$(dirname "$0")/../../.." || exit 1   # -> repo root
PYTHON=/opt/conda/bin/python
SCRIPT=research/eval_v3-1_claim2action/stage2/run_stage2.py
JUDGE=deepseek-v4-pro
TS=$(date -u +%Y%m%dT%H%M%SZ)
LOGDIR=research/eval_v3-1_claim2action/stage2/logs
mkdir -p "$LOGDIR"

# author -> the run_stage2.py args that locate its stage1 + trajectories + output
deepseek_chat_args=(
  --stage1-dir eval_v3-1_claim2action/stage1/results_deepseek_chat
  --ind-dir experiments_v2/real/independent
  --dep-dir experiments_v2/real/dependent
  --traj-suffix _deepseek_deepseek_chat
  --output-dir binary_results_deepseek_chat
)
gpt4o_args=(
  --stage1-dir eval_v3/stage1/results_gpt4o
  --ind-dir experiments_v2/independent
  --dep-dir experiments_v2/dependent
  --traj-suffix _openai_gpt_4o
  --output-dir binary_results_gpt4o
)

run_author() {
  local name="$1"; shift
  local -a args=("$@")
  local smoke="$LOGDIR/${TS}_${name}_smoke.log"
  local full="$LOGDIR/${TS}_${name}_full.log"
  local base=( "$PYTHON" "$SCRIPT" --prompt-version v2 --model "$JUDGE" )

  echo ">>> [$name] smoke (1 task) -> $smoke"
  "${base[@]}" "${args[@]}" --limit 1 >"$smoke" 2>&1
  if grep -q 'api_error' "$smoke"; then
    echo "!!! [$name] smoke hit api_error — aborting (check DEEPSEEK_API_KEY / research/.env)."
    tail -n 8 "$smoke"; return 1
  fi
  echo "    [$name] smoke OK."

  echo ">>> [$name] full run -> $full"
  "${base[@]}" "${args[@]}" >"$full" 2>&1
  local rc=$?
  echo "    [$name] full run exit=$rc; tail:"; tail -n 4 "$full"
  return $rc
}

echo "=== Stage2 v2 batch @ $TS (judge=$JUDGE) ==="
run_author deepseek-chat "${deepseek_chat_args[@]}" || { echo "ABORTED at deepseek-chat"; exit 1; }
run_author gpt-4o        "${gpt4o_args[@]}"         || { echo "ABORTED at gpt-4o"; exit 1; }
echo "=== ALL DONE @ $(date -u +%Y%m%dT%H%M%SZ) ==="
