#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="$repo_root/research/.venv/bin/python"
task_file="$repo_root/research/appworld_backend/tasks/batch_C_teammate.json"
log_file="$repo_root/research/appworld_backend/runs/batch_C_teammate_stage2.log"
checksum_file="$repo_root/research/judge_versions/appworld_experiment_old_judge_20260802/SHA256SUMS"

cd "$repo_root"
sha256sum --check "$checksum_file"

export APPWORLD_ROOT="${APPWORLD_ROOT:-$repo_root/.appworld-root}"
export APPWORLD_CACHE="${APPWORLD_CACHE:-$APPWORLD_ROOT/.cache}"
export PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}"

# Stage 2 must never start from a partial Stage 1 matrix.  The trajectory
# generator is resumable, so a later pipeline restart will fill only the
# missing cells and pass this gate once all five models are present.
"$python_bin" - "$task_file" <<'PY'
import json
import sys

from research.appworld_backend.gen_trajectories import MODELS, RUNS

tasks = json.load(open(sys.argv[1]))
trajectory_stems = [
    path.stem.lower()
    for path in (RUNS / "trajectories").rglob("*.json")
    if "_archive" not in str(path)
]


def trajectory_exists(task, provider, model):
    task_prefix = f"{task.upper().replace('_', '-')}_{provider}_".lower()
    model_tag = model.split("/")[-1].replace("-", "_").replace(".", "_").lower()
    return any(stem.startswith(task_prefix) and model_tag in stem for stem in trajectory_stems)


missing = [
    (task, f"{provider}/{model}")
    for task in tasks
    for provider, model in MODELS
    if not trajectory_exists(task, provider, model)
]
if missing:
    print(
        f"Refusing to start Stage 2: {len(missing)} of "
        f"{len(tasks) * len(MODELS)} trajectory cells are missing.",
        file=sys.stderr,
    )
    for task, model in missing[:20]:
        print(f"  missing {task} / {model}", file=sys.stderr)
    if len(missing) > 20:
        print(f"  ... and {len(missing) - 20} more", file=sys.stderr)
    raise SystemExit(4)
print(f"Stage 1 completeness gate passed: {len(tasks) * len(MODELS)} trajectories.")
PY

if pgrep -f '[j]udge_all.py' >/dev/null; then
  echo "Refusing to start: another judge_all.py process is already active." >&2
  exit 3
fi

task_csv="$($python_bin -c 'import json, sys; print(",".join(json.load(open(sys.argv[1]))))' "$task_file")"

exec > >(tee -a "$log_file") 2>&1
exec "$python_bin" research/appworld_backend/judge_all.py \
  --tasks "$task_csv" \
  --judge gemini-pro \
  --workers 3 \
  --timeout 3600 \
  --retries 3
