#!/usr/bin/env python3
"""Prove two concurrent AppWorld replays do not contaminate each other.

Phase 2 wants to shard the corpus by model tag across processes.  That is only
legitimate if a cell replayed while another world is live in a sibling process
scores exactly what it scores alone.  This script establishes that empirically
rather than by argument:

  1. SERIAL BASELINE -- replay a handful of cells from two different tags, one
     after another, in this process.
  2. CONCURRENT      -- launch one subprocess per tag, both replaying the same
     cells at the same time, each with its own ``experiment_name``.
  3. COMPARE         -- pass_count / num_tests / success must match cell-for-cell.

A single process cannot be its own control here: ``AppWorld.initialize()`` calls
``AppWorld.close_all()``, so opening world B inside the process that holds world A
destroys A.  That is why in-process threading is off the table and why the check
has to cross a process boundary.

Usage
-----
    APPWORLD_ROOT=... PYTHONPATH=$PWD venv/bin/python \
      research/appworld_backend/check_isolation.py [--n 4]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import warnings
from pathlib import Path

os.environ.setdefault("APPWORLD_ROOT", "/Users/maokaifang/appworld-root")
warnings.filterwarnings("ignore")

from research.appworld_backend.replay_lib import load_cells, replay_cell, wall  # noqa: E402

PAIR = ("ds_chat", "gpt4omini")
FIELDS = ("pass_count", "num_tests", "success_strict", "success_state", "replay_errors")


def pick(tag: str, n: int) -> list[dict]:
    """Deterministic pick: the n cells for ``tag`` with the most tool calls, so the
    test exercises long chains rather than one-call no-ops."""
    cells = [c for c in load_cells() if c["tag"] == tag]
    scored = []
    for cell in cells:
        trajectory = json.loads(Path(cell["traj_path"]).read_text())
        n_calls = sum(len(s.get("tool_calls") or []) for s in trajectory.get("steps") or [])
        scored.append((n_calls, cell))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["task"]))
    return [cell for _, cell in scored[:n]]


def replay_many(tag: str, n: int, prefix: str) -> list[dict]:
    out = []
    for cell in pick(tag, n):
        result = replay_cell(cell, experiment_prefix=prefix, gateway=False)
        out.append({"task": cell["task"], "tag": tag, **{f: result[f] for f in FIELDS}})
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=4)
    parser.add_argument("--worker", help="internal: run one tag and print JSON")
    parser.add_argument("--prefix", default="tsriso")
    args = parser.parse_args()

    if args.worker:
        print("@@JSON@@" + json.dumps(replay_many(args.worker, args.n, args.prefix)))
        return 0

    print(f"serial baseline: {PAIR[0]} then {PAIR[1]}, {args.n} cells each")
    started = wall()
    baseline = {}
    for tag in PAIR:
        for row in replay_many(tag, args.n, "tsrisoA"):
            baseline[(row["task"], row["tag"])] = row
    serial_secs = wall() - started
    print(f"  {serial_secs / 60:.1f} min")

    print("concurrent: both tags at once, one subprocess each")
    started = wall()
    procs = [
        subprocess.Popen(
            [sys.executable, __file__, "--worker", tag, "--n", str(args.n), "--prefix", "tsrisoB"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            env={**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "")},
        )
        for tag in PAIR
    ]
    concurrent = {}
    for proc in procs:
        stdout, _ = proc.communicate()
        payload = [line for line in stdout.splitlines() if line.startswith("@@JSON@@")]
        if not payload:
            print(f"  worker produced no result (exit {proc.returncode})")
            return 1
        for row in json.loads(payload[-1][len("@@JSON@@"):]):
            concurrent[(row["task"], row["tag"])] = row
    concurrent_secs = wall() - started
    print(f"  {concurrent_secs / 60:.1f} min  (speedup {serial_secs / max(concurrent_secs, 1e-9):.2f}x)")

    mismatches = []
    for key, base in baseline.items():
        other = concurrent.get(key)
        if other is None:
            mismatches.append((key, "missing from concurrent run"))
            continue
        diff = {f: (base[f], other[f]) for f in FIELDS if base[f] != other[f]}
        if diff:
            mismatches.append((key, diff))

    print("\n" + "=" * 70)
    if mismatches:
        print(f"ISOLATION FAILED: {len(mismatches)}/{len(baseline)} cells differ")
        for key, diff in mismatches[:10]:
            print(f"  {key}: {diff}")
        print("=> stay SERIAL.")
        return 1
    print(f"ISOLATION OK: all {len(baseline)} cells scored identically serial vs concurrent")
    print("=> sharding by tag across processes is safe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
