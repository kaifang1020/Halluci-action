#!/usr/bin/env python3
"""Run hidden-audit v1 experiments with independent and dependent layouts.

Output layout:

    research/experiments_v1/
      independent/<domain>/{trajectories,audits}/...
      dependent/<domain>/<chain>/{trajectories,audits}/...
      run_summaries/<timestamp>.jsonl

Independent tasks get a fresh reset + furnish before each task.
Dependent chains get one reset + furnish at the start of the chain, then run
the tasks in sequence so state can carry forward inside the chain.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_DIR = ROOT_DIR / "research" / "experiments_v1"
SUMMARY_DIR = EXPERIMENTS_DIR / "run_summaries"

INDEPENDENT_TASKS = [
    "S-1", "S-2", "S-3", "S-4", "S-5", "S-6",
    "I-1", "I-2", "I-3", "I-4", "I-5", "I-6",
    "A-1", "A-2", "A-3", "A-4", "A-5",
    "C-1", "C-2", "C-3", "C-4", "C-6",
    "P-1", "P-3", "P-5", "P-6",
    "H-1", "H-2", "H-3", "H-4", "H-5", "H-6",
    "D-1", "D-2", "D-3", "D-4", "D-5", "D-6",
    "PU-1", "PU-2", "PU-3", "PU-6",
    "M-1", "M-3",
    "PR-1", "PR-2", "PR-3", "PR-5",
]

DEPENDENT_CHAINS: dict[str, list[str]] = {
    "A2_A6": ["A-2", "A-6"],
    "C1_C5": ["C-1", "C-5"],
    "C2_P2": ["C-2", "P-2"],
    "P1_P4": ["P-1", "P-4"],
    "PU2_PU4": ["PU-2", "PU-4"],
    "PU3_PU5": ["PU-3", "PU-5"],
    "M1_M2": ["M-1", "M-2"],
    "M3_M4": ["M-3", "M-4"],
    "M1_M5": ["M-1", "M-2", "M-3", "M-4", "M-5"],
    "M1_M6": ["M-1", "M-2", "M-3", "M-4", "M-5", "M-6"],
    "PR1_PR4": ["PR-1", "PR-4"],
    "PR1_PR6": ["PR-1", "PR-2", "PR-3", "PR-4", "PR-5", "PR-6"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["independent", "dependent", "all"], default="all")
    parser.add_argument("--tasks", nargs="*", help="Independent task IDs to run. Defaults to all independent tasks.")
    parser.add_argument("--chains", nargs="*", help="Dependent chain names to run. Defaults to all chains.")
    parser.add_argument("--agent", default=os.environ.get("DEFAULT_AGENT", "deepseek"))
    parser.add_argument("--model", default=os.environ.get("DEFAULT_MODEL", "deepseek-chat"))
    parser.add_argument("--kl", default=os.environ.get("KL", "KL1"))
    parser.add_argument("--max-steps", type=int, default=int(os.environ.get("MAX_STEPS", "15")))
    parser.add_argument("--timeout-sec", type=int, default=300, help="Timeout per task run.")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--no-codebook", action="store_true", help="Pass --no-codebook to the harness.")
    parser.add_argument("--no-reset", action="store_true", help="Do not reset/furnish. Useful only for local debugging.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip a task when a matching trajectory already exists in its target directory.")
    parser.add_argument("--dry-run", action="store_true", help="Print the run plan without changing the DB or running agents.")
    return parser.parse_args()


def load_tasks() -> dict[str, dict[str, Any]]:
    sys.path.insert(0, str(ROOT_DIR))
    from research.tasks import TASKS

    return TASKS


def task_domain(task_id: str, tasks: dict[str, dict[str, Any]]) -> str:
    if task_id not in tasks:
        raise KeyError(f"Unknown task id: {task_id}")
    return str(tasks[task_id]["domain"])


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def append_summary(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def run_command(
    command: list[str],
    *,
    timeout_sec: int | None = None,
    dry_run: bool = False,
    check: bool = False,
) -> tuple[str, int, float]:
    print("+ " + " ".join(command), flush=True)
    if dry_run:
        return "", 0, 0.0
    started = time.time()
    completed = subprocess.run(
        command,
        cwd=ROOT_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout_sec,
    )
    duration = time.time() - started
    if completed.stdout:
        print(completed.stdout, end="", flush=True)
    if check and completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, command, output=completed.stdout)
    return completed.stdout or "", completed.returncode, duration


def reset_and_furnish(args: argparse.Namespace) -> None:
    if args.no_reset:
        print("Skipping reset/furnish because --no-reset was set.", flush=True)
        return

    runtime = os.environ.get("HALLUCI_RUNTIME", "docker")
    if runtime == "hpc":
        reset_script = ROOT_DIR / "scripts" / "reset_hpc.sh"
    elif runtime == "docker":
        reset_script = ROOT_DIR / "scripts" / "reset.sh"
    else:
        raise SystemExit(
            f"Unsupported HALLUCI_RUNTIME={runtime!r}; expected 'docker' or 'hpc'."
        )

    run_command(["bash", str(reset_script)], dry_run=args.dry_run, check=True)
    if args.dry_run:
        run_command([sys.executable, str(ROOT_DIR / "scripts" / "furnish_database.py")], dry_run=True)
        return

    furnish_command = [sys.executable, str(ROOT_DIR / "scripts" / "furnish_database.py")]
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(1, 6):
        if attempt > 1:
            wait_seconds = min(5 * attempt, 20)
            print(f"Furnish retry {attempt}/5 after {wait_seconds}s...", flush=True)
            time.sleep(wait_seconds)
        try:
            run_command(furnish_command, check=True)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
    if last_error:
        raise last_error


def target_runs_dir(mode: str, domain: str, chain: str | None = None) -> Path:
    if mode == "independent":
        return EXPERIMENTS_DIR / "independent" / domain
    if not chain:
        raise ValueError("Dependent runs require a chain name.")
    return EXPERIMENTS_DIR / "dependent" / domain / chain


def matching_trajectory_exists(runs_dir: Path, task_id: str, agent: str, model: str) -> bool:
    stem = f"{task_id}_{slug(agent)}_{slug(model)}"
    trajectories_dir = runs_dir / "trajectories"
    return any(trajectories_dir.glob(f"{stem}*.json"))


def slug(value: str) -> str:
    import re

    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower() or "unknown"


def run_task(
    task_id: str,
    *,
    mode: str,
    domain: str,
    args: argparse.Namespace,
    summary_path: Path,
    chain: str | None = None,
) -> bool:
    runs_dir = target_runs_dir(mode, domain, chain)
    if args.skip_existing and matching_trajectory_exists(runs_dir, task_id, args.agent, args.model):
        print(f"Skipping existing {mode} task {task_id} in {runs_dir}", flush=True)
        if not args.dry_run:
            append_summary(
                summary_path,
                {
                    "timestamp": timestamp(),
                    "mode": mode,
                    "chain": chain,
                    "task_id": task_id,
                    "domain": domain,
                    "status": "skipped_existing",
                    "runs_dir": str(runs_dir),
                },
            )
        return False

    before = set((runs_dir / "trajectories").glob("*.json"))
    command = [
        sys.executable,
        "-m",
        "research.harness",
        "run",
        "--agent",
        args.agent,
        "--model",
        args.model,
        "--task-id",
        task_id,
        "--kl",
        args.kl,
        "--max-steps",
        str(args.max_steps),
        "--runs",
        str(args.runs),
        "--runs-dir",
        str(runs_dir),
    ]
    if args.no_codebook:
        command.append("--no-codebook")

    status = "success"
    output = ""
    duration = 0.0
    try:
        output, returncode, duration = run_command(command, timeout_sec=args.timeout_sec, dry_run=args.dry_run)
        if returncode != 0:
            status = "failed"
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        duration = float(args.timeout_sec)
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else (exc.stdout or b"").decode(errors="replace")
        if output:
            print(output, end="", flush=True)
        print(f"TIMEOUT after {args.timeout_sec}s: {task_id}", flush=True)

    after = set((runs_dir / "trajectories").glob("*.json"))
    new_trajectories = sorted(after - before, key=lambda path: path.stat().st_mtime) if not args.dry_run else []
    if not args.dry_run:
        append_summary(
            summary_path,
            {
                "timestamp": timestamp(),
                "mode": mode,
                "chain": chain,
                "task_id": task_id,
                "domain": domain,
                "agent": args.agent,
                "model": args.model,
                "status": status,
                "duration_sec": round(duration, 3),
                "runs_dir": str(runs_dir),
                "trajectories": [str(path) for path in new_trajectories],
            },
        )

    if status != "success" and not args.dry_run:
        log_dir = SUMMARY_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_name = f"{timestamp()}_{mode}_{chain or 'none'}_{task_id}.log"
        (log_dir / log_name).write_text(output, encoding="utf-8")
    return True


def run_independent(args: argparse.Namespace, tasks: dict[str, dict[str, Any]], summary_path: Path) -> None:
    selected = args.tasks or INDEPENDENT_TASKS
    for index, task_id in enumerate(selected, start=1):
        domain = task_domain(task_id, tasks)
        print(f"\n[{index}/{len(selected)}] independent {task_id} ({domain})", flush=True)
        runs_dir = target_runs_dir("independent", domain)
        if args.skip_existing and matching_trajectory_exists(runs_dir, task_id, args.agent, args.model):
            run_task(task_id, mode="independent", domain=domain, args=args, summary_path=summary_path)
            continue
        try:
            reset_and_furnish(args)
        except subprocess.CalledProcessError as exc:
            print(f"Reset/furnish failed for {task_id}; skipping task.", flush=True)
            if not args.dry_run:
                append_summary(
                    summary_path,
                    {
                        "timestamp": timestamp(),
                        "mode": "independent",
                        "chain": None,
                        "task_id": task_id,
                        "domain": domain,
                        "agent": args.agent,
                        "model": args.model,
                        "status": "reset_or_furnish_failed",
                        "returncode": exc.returncode,
                    },
                )
            continue
        run_task(task_id, mode="independent", domain=domain, args=args, summary_path=summary_path)


def run_dependent(args: argparse.Namespace, tasks: dict[str, dict[str, Any]], summary_path: Path) -> None:
    chain_names = args.chains or list(DEPENDENT_CHAINS)
    for chain_index, chain_name in enumerate(chain_names, start=1):
        if chain_name not in DEPENDENT_CHAINS:
            raise KeyError(f"Unknown chain: {chain_name}")
        task_ids = DEPENDENT_CHAINS[chain_name]
        print(f"\n[{chain_index}/{len(chain_names)}] dependent chain {chain_name}: {' '.join(task_ids)}", flush=True)
        try:
            reset_and_furnish(args)
        except subprocess.CalledProcessError as exc:
            print(f"Reset/furnish failed for chain {chain_name}; skipping chain.", flush=True)
            if not args.dry_run:
                append_summary(
                    summary_path,
                    {
                        "timestamp": timestamp(),
                        "mode": "dependent",
                        "chain": chain_name,
                        "task_id": None,
                        "domain": None,
                        "agent": args.agent,
                        "model": args.model,
                        "status": "reset_or_furnish_failed",
                        "returncode": exc.returncode,
                    },
                )
            continue
        for task_id in task_ids:
            domain = task_domain(task_id, tasks)
            run_task(
                task_id,
                mode="dependent",
                domain=domain,
                chain=chain_name,
                args=args,
                summary_path=summary_path,
            )


def main() -> None:
    args = parse_args()
    tasks = load_tasks()
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = SUMMARY_DIR / f"{timestamp()}_{args.mode}_{args.agent}_{slug(args.model)}.jsonl"

    print(f"Summary: {summary_path}", flush=True)
    print(f"Agent/model: {args.agent} / {args.model}", flush=True)
    print(f"Mode: {args.mode}", flush=True)
    if args.dry_run:
        print("DRY RUN: no database reset, furnish, or agent calls will be executed.", flush=True)

    if args.mode in {"independent", "all"}:
        run_independent(args, tasks, summary_path)
    if args.mode in {"dependent", "all"}:
        run_dependent(args, tasks, summary_path)


if __name__ == "__main__":
    main()
