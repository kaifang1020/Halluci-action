#!/usr/bin/env python3
"""Phase 1: does replaying a recorded trajectory reproduce the original run?

Answering "did this agent complete the task?" by replay is only meaningful if the
replay lands the environment in the state the original run left it in.  This
script checks that directly, on a stratified sample, before anything is scaled up.

What it measures per sampled cell
---------------------------------
1. replay error rate      -- calls that failed, over calls attempted, alongside the
                             number that ALSO failed in the original run (a call
                             that errored then and errors now is a match, not a bug).
2. determinism            -- every action's ``state_delta`` from the replay is
                             compared against the delta the original run recorded
                             in ``runs/audits/<stem>__audit.json`` under
                             ``records[].gateway_result.state_delta``.  Both a
                             strict comparison (full row contents, ids, timestamps)
                             and a structural one ({table, op, id}) are reported.
3. wall-clock             -- including ``AppWorld(...)`` construction and ``close()``.
4. success distribution   -- over the sample.

Plus a NULL-REPLAY CONTROL on every sampled cell that has at least one write:
build the world, replay nothing, evaluate.  If the control scored the same as the
replay, the evaluator would not be reading our writes and the whole exercise
would be void.

Usage
-----
    cd <repo root>
    APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
      /Users/maokaifang/appworld-root/venv/bin/python \
      research/appworld_backend/phase1_validate.py [--n 30]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

os.environ.setdefault("APPWORLD_ROOT", "/Users/maokaifang/appworld-root")
warnings.filterwarnings("ignore")

from research.appworld_backend.replay_lib import (  # noqa: E402
    RUNS,
    TAGS,
    compare_to_audit,
    extract_calls,
    load_audit_records,
    load_cells,
    replay_cell,
    wall,
)

OUT = RUNS / "phase1_determinism.json"


def profile(cell: dict) -> dict:
    """n_calls + the dominant app, read straight off the trajectory file."""
    trajectory = json.loads(Path(cell["traj_path"]).read_text())
    calls = extract_calls(trajectory)
    apps = Counter(name.split("__", 1)[0] for name, _ in calls)
    return {
        "n_calls": len(calls),
        "app": apps.most_common(1)[0][0] if apps else "none",
        "n_writes": sum(
            1
            for record in load_audit_records(cell["audit_path"])
            if (record.get("gateway_result") or {}).get("state_delta")
        ),
    }


def sample(cells: list[dict], n: int, seed: int = 20260811) -> list[dict]:
    """Stratified: all five tags, a spread of apps, a spread of lengths, and the
    three longest trajectories in the whole corpus (the worst case for drift)."""
    rng = random.Random(seed)
    enriched = []
    for cell in cells:
        enriched.append({**cell, **profile(cell)})

    chosen: dict[tuple[str, str], dict] = {}

    # the three longest cells overall -- longest chains have the most room to diverge
    for cell in sorted(enriched, key=lambda c: -c["n_calls"])[:3]:
        chosen[(cell["task"], cell["tag"])] = cell

    # every tag, spread over apps and over length terciles
    by_tag: dict[str, list[dict]] = defaultdict(list)
    for cell in enriched:
        by_tag[cell["tag"]].append(cell)
    per_tag = max(1, (n - len(chosen)) // len(TAGS))
    for tag in TAGS:
        pool = [c for c in by_tag[tag] if c["n_calls"] > 0]
        pool.sort(key=lambda c: c["n_calls"])
        if not pool:
            continue
        # take from the short / middle / long thirds, preferring write-heavy cells
        thirds = [pool[: len(pool) // 3 or 1], pool[len(pool) // 3 : 2 * len(pool) // 3 or 1], pool[2 * len(pool) // 3 :]]
        picked_apps: set[str] = set()
        for third in thirds:
            if not third:
                continue
            ranked = sorted(third, key=lambda c: (c["app"] in picked_apps, -c["n_writes"], rng.random()))
            for cell in ranked[: max(1, per_tag // 3 + 1)]:
                chosen[(cell["task"], cell["tag"])] = cell
                picked_apps.add(cell["app"])

    out = list(chosen.values())
    rng.shuffle(out)
    return out[: max(n, len(out) if len(out) < n else n)]


def null_control(cell: dict) -> dict:
    """Construct the world, replay NOTHING, evaluate.  The floor score."""
    from appworld import AppWorld

    world = AppWorld(task_id=cell["task"], experiment_name=f"tsrnull_{cell['tag']}")
    try:
        tracker = world.evaluate(suppress_errors=True)
        from research.appworld_backend.replay_lib import answer_test_split
        split = answer_test_split(tracker)
        return {"pass_count": int(tracker.pass_count), "num_tests": int(tracker.num_tests),
                "success_strict": bool(tracker.success),
                "success_state": split["success_state"],
                "state_pass_count": split["state_pass_count"],
                "state_num_tests": split["state_num_tests"]}
    finally:
        try:
            world.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--controls", type=int, default=8,
                        help="how many of the sampled cells also get a null-replay control")
    args = parser.parse_args()

    cells = load_cells()
    picked = sample(cells, args.n)
    print(f"corpus: {len(cells)} judged cells; sampling {len(picked)}")
    print(f"  tags : {Counter(c['tag'] for c in picked)}")
    print(f"  apps : {Counter(c['app'] for c in picked)}")
    lengths = [c["n_calls"] for c in picked]
    print(f"  calls: min={min(lengths)} median={statistics.median(lengths)} max={max(lengths)}")

    results = []
    control_budget = args.controls
    for index, cell in enumerate(picked, 1):
        try:
            replay = replay_cell(cell, experiment_prefix="tsr1", gateway=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[{index:>2}/{len(picked)}] {cell['task']:<12} {cell['tag']:<12} REPLAY FAILED: {exc}")
            results.append({"task": cell["task"], "tag": cell["tag"], "traj": cell["traj"],
                            "fatal": f"{type(exc).__name__}: {exc}"})
            continue

        records = load_audit_records(cell["audit_path"])
        comparison = compare_to_audit(replay["observed"], records)
        original_errors = sum(
            1 for record in records
            if (record.get("gateway_result") or {}).get("status") != "success"
        )

        control = None
        if control_budget > 0 and cell["n_writes"] > 0:
            try:
                started = wall()
                control = null_control(cell)
                control["secs"] = round(wall() - started, 2)
                control_budget -= 1
            except Exception as exc:  # noqa: BLE001
                control = {"error": f"{type(exc).__name__}: {exc}"}

        row = {
            "task": cell["task"], "tag": cell["tag"], "traj": cell["traj"],
            "app": cell["app"], "n_calls": replay["n_calls"], "n_writes": cell["n_writes"],
            "replay_errors": replay["replay_errors"], "original_errors": original_errors,
            "success_strict": replay["success_strict"], "success_state": replay["success_state"],
            "answer_test_failed": replay["answer_test_failed"],
            "failed_requirements": replay["failed_requirements"],
            "pass_count": replay["pass_count"],
            "num_tests": replay["num_tests"], "pass_percentage": replay["pass_percentage"],
            "secs": replay["secs"], "determinism": comparison, "null_control": control,
        }
        results.append(row)
        flag = "EXACT" if comparison["cell_exact"] else ("STRUCT" if comparison["cell_structural"] else "DIFF")
        ctrl = "" if control is None else f" ctrl={control.get('pass_count')}/{control.get('num_tests')}"
        print(
            f"[{index:>2}/{len(picked)}] {cell['task']:<12} {cell['tag']:<12} "
            f"calls={replay['n_calls']:>3} err={replay['replay_errors']:>2}/{original_errors:<2} "
            f"delta={comparison['exact']}/{comparison['n_compared']} {flag:<6} "
            f"pass={replay['pass_count']}/{replay['num_tests']} "
            f"strict={str(replay['success_strict']):<5} state={str(replay['success_state']):<5} "
            f"{replay['secs']:>6.1f}s{ctrl}"
        )
        sys.stdout.flush()

    summarise(results)
    OUT.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {OUT}")
    return 0


def summarise(results: list[dict]) -> None:
    ok = [r for r in results if "fatal" not in r]
    print("\n" + "=" * 78)
    print(f"PHASE 1 SUMMARY  ({len(ok)} replayed, {len(results) - len(ok)} fatal)")
    print("=" * 78)
    if not ok:
        return

    calls = sum(r["n_calls"] for r in ok)
    errs = sum(r["replay_errors"] for r in ok)
    orig = sum(r["original_errors"] for r in ok)
    print(f"1. replay error rate : {errs}/{calls} = {100 * errs / max(calls, 1):.1f}% "
          f"(original run: {orig}/{calls} = {100 * orig / max(calls, 1):.1f}%)")

    exact_cells = sum(r["determinism"]["cell_exact"] for r in ok)
    struct_cells = sum(r["determinism"]["cell_structural"] for r in ok)
    aligned = sum(r["determinism"]["aligned"] for r in ok)
    a_exact = sum(r["determinism"]["exact"] for r in ok)
    a_struct = sum(r["determinism"]["structural"] for r in ok)
    a_n = sum(r["determinism"]["n_compared"] for r in ok)
    write_cells = [r for r in ok if r["n_writes"] > 0]
    print(f"2. determinism       : cells strict-identical  {exact_cells}/{len(ok)} "
          f"({100 * exact_cells / len(ok):.1f}%)")
    print(f"                       cells structurally same {struct_cells}/{len(ok)}")
    print(f"                       actions strict-identical {a_exact}/{a_n} "
          f"({100 * a_exact / max(a_n, 1):.1f}%), structural {a_struct}/{a_n}")
    print(f"                       action alignment ok in {aligned}/{len(ok)} cells")
    if write_cells:
        we = sum(r["determinism"]["cell_exact"] for r in write_cells)
        print(f"                       write-bearing cells strict-identical {we}/{len(write_cells)}")

    secs = [r["secs"] for r in ok]
    print(f"3. wall-clock / cell : mean {statistics.mean(secs):.1f}s  "
          f"median {statistics.median(secs):.1f}s  min {min(secs):.1f}s  max {max(secs):.1f}s "
          f"(gateway snapshots ON; the bulk run turns them off)")

    strict = Counter(r["success_strict"] for r in ok)
    state = Counter(r["success_state"] for r in ok)
    ans = sum(r["answer_test_failed"] for r in ok)
    print(f"4. success (strict)  : True {strict[True]}  False {strict[False]}  "
          f"({100 * strict[True] / len(ok):.1f}%)")
    print(f"   success (state)   : True {state[True]}  False {state[False]}  "
          f"({100 * state[True] / len(ok):.1f}%)  -- answer test excluded")
    print(f"   answer test failed in {ans}/{len(ok)} cells "
          f"(the harness never calls supervisor.complete_task)")
    pct = [r["pass_percentage"] for r in ok]
    print(f"   pass_percentage   : mean {statistics.mean(pct):.1f}  median {statistics.median(pct):.1f}")

    controls = [r for r in ok if isinstance(r.get("null_control"), dict) and "pass_count" in r["null_control"]]
    if controls:
        moved = sum(1 for r in controls if r["null_control"]["pass_count"] != r["pass_count"])
        print(f"5. null-replay ctrl  : {moved}/{len(controls)} write-bearing cells score DIFFERENTLY "
              f"with no replay -- i.e. the evaluator does read the replayed writes")
        for r in controls:
            print(f"     {r['task']:<12} {r['tag']:<12} null={r['null_control']['pass_count']}/"
                  f"{r['null_control']['num_tests']}  replay={r['pass_count']}/{r['num_tests']}")

    bad = [r for r in ok if not r["determinism"]["cell_exact"]]
    if bad:
        print(f"\nfirst mismatching cells ({len(bad)} total):")
        for r in bad[:6]:
            print(f"  {r['task']} {r['tag']} ({r['app']}, {r['n_calls']} calls) "
                  f"exact={r['determinism']['exact']}/{r['determinism']['n_compared']}")
            for m in r["determinism"]["mismatches"][:2]:
                print(f"     #{m['i']} {m['tool_name']} structural={m['structural']}")
                print(f"        obs tables {m['obs_tables']}")
                print(f"        rec tables {m['rec_tables']}")


if __name__ == "__main__":
    raise SystemExit(main())
