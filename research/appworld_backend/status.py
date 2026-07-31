#!/usr/bin/env python3
"""Report what has actually been run, by counting artifacts on disk.

Any status written into a document is stale the moment judging advances, so this
recomputes from `runs/` instead. Run it before claiming work:

    APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
      <venv>/bin/python research/appworld_backend/status.py

    # only one batch
    ... status.py --batch A

    # print the task ids that still need work, ready to paste into --tasks
    ... status.py --todo trajectories
    ... status.py --todo judge

A cell is one (task, model) pair. Stage 1 produces a trajectory; stage 2 produces
`pipeline_<task>_<tag>.html`. Both stages skip finished cells, so re-running is safe.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
RUNS = BASE / "runs"
TASKS = BASE / "tasks"

# Keep in step with judge_all.MODEL_TAG.
MODEL_TAG = {
    "deepseek-chat": "ds_chat",
    "deepseek-reasoner": "ds_reasoner",
    "qwen3-8b": "qwen8b",
    "@vertexai-hs3645/gemini-3-flash-preview": "gemflash",
    "gpt-4o-mini": "gpt4omini",
}
TAGS = ["ds_chat", "ds_reasoner", "qwen8b", "gemflash", "gpt4omini"]

BATCHES = {
    "A": ("batch_A_baseline_100.json", "baseline"),
    "B": ("batch_B_expansion_55.json", "expansion"),
}


def _load(name: str) -> list[str]:
    path = TASKS / name
    if not path.exists():
        raise SystemExit(f"missing task list: {path}")
    return json.loads(path.read_text())


def scan() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(task -> tags with a trajectory, task -> tags judged). Archived runs excluded."""
    traj: dict[str, set[str]] = collections.defaultdict(set)
    judged: dict[str, set[str]] = collections.defaultdict(set)
    for f in glob.glob(str(RUNS / "trajectories" / "**" / "*.json"), recursive=True):
        if "_archive" in f:
            continue
        try:
            t = json.loads(Path(f).read_text())
        except Exception:  # noqa: BLE001 - a half-written file just isn't counted yet
            continue
        tid, model = t.get("task_id"), t.get("model")
        if tid and model in MODEL_TAG:
            traj[tid].add(MODEL_TAG[model])
    for f in glob.glob(str(RUNS / "pipeline_*.html")):
        m = re.match(r"pipeline_(.+)_(" + "|".join(TAGS) + r")\.html", Path(f).name)
        if m:
            judged[m.group(1)].add(m.group(2))
    return traj, judged


def report(tasks: list[str], label: str, traj, judged) -> None:
    n = len(tasks) * len(TAGS)
    tc = sum(len(traj[t] & set(TAGS)) for t in tasks)
    jc = sum(len(judged[t] & set(TAGS)) for t in tasks)
    ready = sum(1 for t in tasks for m in traj[t] if m in TAGS and m not in judged[t])
    print(f"\n=== {label}: {len(tasks)} tasks / {n} cells ===")
    print(f"  trajectories  {tc:>4d}/{n}  ({100 * tc / n:5.1f}%)   "
          f"all 5 models: {sum(1 for t in tasks if len(traj[t] & set(TAGS)) == 5)}/{len(tasks)}")
    print(f"  judged        {jc:>4d}/{n}  ({100 * jc / n:5.1f}%)   "
          f"all 5 models: {sum(1 for t in tasks if len(judged[t] & set(TAGS)) == 5)}/{len(tasks)}")
    print(f"  ready to judge now   {ready:>4d}")
    print(f"  still need a trajectory {n - tc:>4d}")
    print("  by model:")
    for tag in TAGS:
        t_n = sum(1 for t in tasks if tag in traj[t])
        j_n = sum(1 for t in tasks if tag in judged[t])
        print(f"    {tag:12s} traj {t_n:>3d}/{len(tasks)}   judged {j_n:>3d}/{len(tasks)}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--batch", choices=["A", "B", "all"], default="all")
    p.add_argument("--todo", choices=["trajectories", "judge"],
                   help="print comma-separated task ids that still need this stage")
    args = p.parse_args()

    traj, judged = scan()
    batches = list(BATCHES) if args.batch == "all" else [args.batch]
    all_tasks: list[str] = []
    for b in batches:
        fname, label = BATCHES[b]
        tasks = _load(fname)
        all_tasks += tasks
        if not args.todo:
            report(tasks, f"batch {b} ({label})", traj, judged)

    if args.todo == "trajectories":
        todo = [t for t in all_tasks if len(traj[t] & set(TAGS)) < len(TAGS)]
    elif args.todo == "judge":
        todo = [t for t in all_tasks if any(m in traj[t] and m not in judged[t] for m in TAGS)]
    else:
        if args.batch == "all":
            report(all_tasks, "TOTAL", traj, judged)
        pool = TASKS / "available_pool.json"
        if pool.exists():
            rest = json.loads(pool.read_text())
            by_split = collections.Counter(r["split"] for r in rest)
            print(f"\n=== unclaimed pool: {len(rest)} tasks (one variant per template) ===")
            print(f"  {dict(by_split)}")
            print(f"  see {pool.relative_to(BASE.parent.parent)}")
        return

    print(",".join(sorted(todo)))


if __name__ == "__main__":
    main()
