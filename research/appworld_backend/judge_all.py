"""Batch JUDGE runner: judge every existing trajectory with the real judge (gemini-3.1-pro).

Trajectories are already on disk (see gen_trajectories.py); this only runs the JUDGE
chain on them via ``run_pipeline.py --traj`` (which skips the agent step entirely).

  * resumable: a cell whose pipeline UI already exists is SKIPPED, so re-running resumes.
  * resilient: per-cell try/except + timeout; one bad cell never kills the batch.
  * every cell's HAR / precision / recall / forbidden counts are appended to
    ``runs/judge_summary.jsonl`` for the by-model comparison.

Usage:
    APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
    <venv>/bin/python research/appworld_backend/judge_all.py [--limit N] [--models ds_chat,...]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
RUNS = BASE / "runs"
SUMMARY = RUNS / "judge_summary.jsonl"

# short, filesystem-safe tag per agent model (the raw gemini id contains "@" and "/")
MODEL_TAG = {
    "deepseek-chat": "ds_chat",
    "deepseek-reasoner": "ds_reasoner",
    "qwen3-8b": "qwen8b",
    "@vertexai-hs3645/gemini-3-flash-preview": "gemflash",
    "gpt-4o-mini": "gpt4omini",
}


def _cells() -> list[dict]:
    """Every active (non-archived) trajectory, deduped to ONE cell per (task, model).

    A few task/model pairs have repeat runs (``_r02``/``_r03``…) left over from
    development. They all share the same output tag, so judging each would just
    overwrite the previous one — pick the newest and judge that.
    """
    best: dict[tuple[str, str], dict] = {}
    for f in sorted(glob.glob(str(RUNS / "trajectories" / "**" / "*.json"), recursive=True)):
        if "_archive" in f:
            continue
        try:
            tj = json.loads(Path(f).read_text())
        except Exception:  # noqa: BLE001
            continue
        task, model = tj.get("task_id"), tj.get("model")
        if not task or model not in MODEL_TAG:
            continue
        key = (task, MODEL_TAG[model])
        cell = {"traj": Path(f), "task": task, "provider": tj.get("agent", ""),
                "model": model, "tag": MODEL_TAG[model]}
        prev = best.get(key)
        if prev is None or os.path.getmtime(f) > os.path.getmtime(prev["traj"]):
            best[key] = cell
    return [best[k] for k in sorted(best)]


def _grab(pat: str, text: str):
    m = re.search(pat, text, re.I)
    return m.group(1) if m else None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--limit", type=int, default=None, help="judge at most N cells (for timing a pilot)")
    p.add_argument("--models", default=None, help="comma-separated short tags (ds_chat,qwen8b,…)")
    p.add_argument("--tasks", default=None, help="comma-separated task ids")
    p.add_argument("--judge", default="gemini-pro")
    p.add_argument("--timeout", type=int, default=3600, help="per-cell seconds")
    p.add_argument("--retries", type=int, default=3,
                   help="retry a cell this many times on TRANSIENT net errors (backoff 30/60/120s)")
    # An earlier 4-worker batch lost 56/60 cells to APITimeoutError, which was read as "the
    # gateway serialises requests". That diagnosis was WRONG. A 2-vs-1 probe against the NYU
    # gateway measured a clean 2.00x speedup (20.6 -> 41.3 req/min) -- it concurrs fine. The
    # real ceiling was ours: the judge modules used the OpenAI SDK default timeout (600s) and
    # hardcoded urlopen timeouts (120s/180s), all well under a cell's real 500-900s runtime,
    # so queued calls died as soon as anything ran in parallel. Those are now widened at
    # runtime (see run_pipeline / run_action_centric / run_requirement), making workers usable.
    p.add_argument("--workers", type=int, default=3,
                   help="cells judged concurrently; gateway scales ~linearly, 3-4 is a safe default")
    args = p.parse_args()

    cells = _cells()
    if args.models:
        keep = set(args.models.split(","))
        cells = [c for c in cells if c["tag"] in keep]
    if args.tasks:
        keep = set(args.tasks.split(","))
        cells = [c for c in cells if c["task"] in keep]

    env = {**os.environ, "APPWORLD_ROOT": os.environ.get("APPWORLD_ROOT", "/Users/maokaifang/appworld-root"),
           "PYTHONPATH": str(REPO)}
    todo = [c for c in cells if not (RUNS / f"pipeline_{c['task']}_{c['tag']}.html").exists()]
    print(f"cells={len(cells)}  already judged={len(cells)-len(todo)}  to judge={len(todo)}")
    if args.limit:
        todo = todo[: args.limit]
        print(f"  (pilot: judging {len(todo)})")

    # ~8 min/cell serially, so the batch is API-bound, not CPU-bound: run cells concurrently.
    lock = threading.Lock()
    ok, failed, t0, done_n = 0, [], time.time(), 0

    # A dropped/blip'd gateway connection is transient: the NYU gateway went unreachable
    # mid-run once and every remaining cell died instantly with APIConnectionError, losing
    # ~40 cells of a serial batch. Retry those in place with backoff so a blip costs minutes,
    # not the rest of the run. Non-transient failures (bugs, bad inputs) are NOT retried.
    _TRANSIENT = ("APIConnectionError", "APITimeoutError", "ConnectionError", "Connection reset",
                  "Connection aborted", "timed out", "Read timed out", " 502", " 503", " 504",
                  "Temporary failure in name resolution", "Remote end closed")

    def _judge_one(c: dict):
        nonlocal ok, done_n
        t1 = time.time()
        cmd = [sys.executable, str(BASE / "run_pipeline.py"), "--task-id", c["task"],
               "--traj", str(c["traj"]), "--tag", c["tag"], "--judge", args.judge,
               "--provider", c["provider"], "--model", c["model"]]
        r = None
        last_tail = ""
        for attempt in range(args.retries + 1):
            try:
                r = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True,
                                   timeout=args.timeout)
            except subprocess.TimeoutExpired:
                with lock:
                    done_n += 1
                    print(f"[{done_n}/{len(todo)}] {c['task']}/{c['tag']}  !! TIMEOUT {args.timeout}s", flush=True)
                    failed.append((c["task"], c["tag"], "timeout"))
                return
            if r.returncode == 0:
                break
            last_tail = (r.stderr or r.stdout).strip()
            is_transient = any(sig in last_tail for sig in _TRANSIENT)
            if is_transient and attempt < args.retries:
                wait = 30 * (2 ** attempt)  # 30s, 60s, 120s, ...
                with lock:
                    print(f"    …{c['task']}/{c['tag']} transient net error, retry "
                          f"{attempt+1}/{args.retries} in {wait}s", flush=True)
                time.sleep(wait)
                continue
            tail = last_tail.splitlines()[-3:]
            with lock:
                done_n += 1
                print(f"[{done_n}/{len(todo)}] {c['task']}/{c['tag']}  !! rc={r.returncode}: "
                      f"{' | '.join(tail)[:180]}", flush=True)
                failed.append((c["task"], c["tag"], f"rc={r.returncode}"))
            return
        out = r.stdout
        rec = {
            "task": c["task"], "tag": c["tag"], "model": c["model"],
            "traj": c["traj"].name,
            "har": _grab(r"HAR=([0-9.]+|None)", out),
            "precision": _grab(r"precision=([0-9.]+|None)", out),
            "recall": _grab(r"recall=([0-9.]+|None)", out),
            "over_claims": _grab(r"over-claims=([0-9]+|None)", out),
            "silent": _grab(r"silent=([0-9]+|None)", out),
            "forbidden": _grab(r"policy:\s+([0-9]+) forbidden", out),
            "covert": _grab(r"\(([0-9]+) covert\)", out),
            "fidelity": _grab(r"fidelity:\s+(\{[^}]*\})", out),
            "secs": round(time.time() - t1, 1),
        }
        with lock:
            done_n += 1
            ok += 1
            with SUMMARY.open("a") as fh:
                fh.write(json.dumps(rec) + "\n")
            print(f"[{done_n}/{len(todo)}] {c['task']}/{c['tag']}  HAR={rec['har']} "
                  f"prec={rec['precision']} rec={rec['recall']} forbidden={rec['forbidden']} "
                  f"({rec['secs']}s)", flush=True)

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(_judge_one, todo))

    el = time.time() - t0
    print(f"\n=== JUDGED === ok={ok} failed={len(failed)} ({el:.0f}s, "
          f"{el/max(ok,1):.0f}s/cell)")
    for t, m, e in failed:
        print(f"  !! {t}/{m}: {e}")
    print(f"  summary: {SUMMARY}")


if __name__ == "__main__":
    main()
