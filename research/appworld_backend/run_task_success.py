#!/usr/bin/env python3
"""Phase 2: replay every judged cell and record AppWorld's own task verdict.

Writes ``runs/task_success.jsonl`` (one object per judged ``(task, tag)`` cell).
Resumable: cells already in the output file are skipped, and every row is
appended + fsynced as it completes, so a crash loses at most the cell in flight.

No LLM is called.  Nothing outside ``research/appworld_backend/`` is written.

Concurrency
-----------
``AppWorld.initialize()`` calls ``AppWorld.close_all()``, so one process can hold
only one open world -- threads are out.  Cross-process sharding IS safe as long as
no two workers touch the same ``(experiment_name, task_id)``: the in-memory app DBs
are per-process and the on-disk output tree is keyed by
``<experiment_name>/tasks/<task_id>``.  ``--shard tag`` gives each model tag its own
experiment name and its own output file, which guarantees that.  ``verify_isolation``
in ``check_isolation.py`` was run first and reproduced serial results exactly.

Usage
-----
    # one tag (what the parallel driver launches, five at a time)
    APPWORLD_ROOT=... PYTHONPATH=$PWD venv/bin/python \
      research/appworld_backend/run_task_success.py --tag ds_chat

    # everything, serially, into the single canonical file
    ... run_task_success.py

    # merge the per-tag shard files into runs/task_success.jsonl
    ... run_task_success.py --merge
"""

from __future__ import annotations

import argparse
import os
import sys
import warnings
from collections import Counter
from pathlib import Path

os.environ.setdefault("APPWORLD_ROOT", "/Users/maokaifang/appworld-root")
warnings.filterwarnings("ignore")

from research.appworld_backend.replay_lib import (  # noqa: E402
    RUNS,
    TAGS,
    append_jsonl,
    load_cells,
    read_jsonl,
    replay_cell,
    wall,
)

OUT = RUNS / "task_success.jsonl"

# Only these keys go into the output file.  ``observed`` (the per-action replay
# trace) is deliberately dropped: it is large and phase 1 already established that
# it reproduces the recorded audit exactly.
KEEP = (
    "task", "tag", "traj", "success", "success_strict", "success_state",
    "pass_count", "fail_count", "num_tests", "pass_percentage",
    "state_pass_count", "state_num_tests", "answer_test_failed", "n_answer_tests",
    "n_calls", "replay_errors", "secs", "failed_requirements",
)


def shard_path(tag: str | None) -> Path:
    return OUT if tag is None else RUNS / f"task_success__{tag}.jsonl"


def run(tag: str | None, limit: int | None = None) -> int:
    path = shard_path(tag)
    done = {(row["task"], row["tag"]) for row in read_jsonl(path)}
    cells = [c for c in load_cells() if tag is None or c["tag"] == tag]
    todo = [c for c in cells if (c["task"], c["tag"]) not in done]
    if limit:
        todo = todo[:limit]

    print(f"[{tag or 'all'}] {len(cells)} cells, {len(done)} already done, {len(todo)} to run -> {path.name}")
    started = wall()
    counts: Counter = Counter()

    for index, cell in enumerate(todo, 1):
        try:
            result = replay_cell(cell, experiment_prefix="tsr", gateway=False)
            # ``success`` is the headline field the downstream join reads.  It is
            # ``success_state``: every non-answer AppWorld test passes.  The raw
            # verdict is kept alongside as ``success_strict``.  See replay_lib's
            # module docstring, artifact 2, for why the two differ.
            result["success"] = result["success_state"]
            row = {key: result[key] for key in KEEP if key in result}
        except Exception as exc:  # noqa: BLE001
            row = {
                "task": cell["task"], "tag": cell["tag"], "traj": cell["traj"],
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }
            counts["fatal"] += 1
        append_jsonl(path, row)
        counts["done"] += 1
        counts[f"success={row.get('success')}"] += 1

        if index % 25 == 0 or index == len(todo):
            elapsed = wall() - started
            rate = elapsed / index
            print(f"[{tag or 'all'}] {index}/{len(todo)}  {elapsed / 60:.1f} min  "
                  f"{rate:.1f}s/cell  eta {(len(todo) - index) * rate / 60:.0f} min  "
                  f"{dict(counts)}")
            sys.stdout.flush()

    print(f"[{tag or 'all'}] finished: {dict(counts)} in {(wall() - started) / 60:.1f} min")
    return 0


def merge() -> int:
    """Fold the per-tag shard files into the canonical ``task_success.jsonl``."""
    rows: dict[tuple[str, str], dict] = {}
    for row in read_jsonl(OUT):
        rows[(row["task"], row["tag"])] = row
    for tag in TAGS:
        for row in read_jsonl(shard_path(tag)):
            rows[(row["task"], row["tag"])] = row
    ordered = sorted(rows.values(), key=lambda r: (r["task"], r["tag"]))
    OUT.write_text("".join(__import__("json").dumps(r) + "\n" for r in ordered))
    errors = sum(1 for r in ordered if "error" in r)
    print(f"merged {len(ordered)} cells into {OUT} ({errors} with a replay error)")
    return 0


def parallel(limit: int | None) -> int:
    """One subprocess per model tag, then merge.  Safe only because each tag gets
    its own ``experiment_name`` and its own shard file -- see the module docstring
    and ``check_isolation.py``."""
    import subprocess

    logs = RUNS / "task_success_logs"
    logs.mkdir(exist_ok=True)
    procs = []
    for tag in TAGS:
        command = [sys.executable, __file__, "--tag", tag]
        if limit:
            command += ["--limit", str(limit)]
        handle = (logs / f"{tag}.log").open("w")
        procs.append((tag, subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT,
                                            env=dict(os.environ)), handle))
        print(f"launched {tag} -> {logs / f'{tag}.log'}")
    failed = []
    for tag, proc, handle in procs:
        code = proc.wait()
        handle.close()
        print(f"{tag} exited {code}")
        if code != 0:
            failed.append(tag)
    if failed:
        print(f"WARNING: shards failed: {failed} (re-run them; the run is resumable)")
    return merge()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", choices=TAGS, help="run only this model tag, into its own shard file")
    parser.add_argument("--limit", type=int, help="stop after this many cells (smoke testing)")
    parser.add_argument("--merge", action="store_true", help="merge shard files and exit")
    parser.add_argument("--parallel", action="store_true", help="one subprocess per tag, then merge")
    args = parser.parse_args()
    if args.merge:
        return merge()
    if args.parallel:
        return parallel(args.limit)
    return run(args.tag, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
