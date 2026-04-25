#!/usr/bin/env python3
"""
Batch runner for Halluci-Action experiments.

Runs a configurable batch of tasks (default: S-1..S-6, I-1..I-6).
Before each task the database is reset to a clean state and re-furnished
with the full task dataset (including noisy background data).

Usage examples:
  python run_batch.py --agent openai --model gpt-4o
  python run_batch.py --agent deepseek --model deepseek-chat --kl KL2
  python run_batch.py --agent openai --model gpt-4o --tasks S-1 S-2 I-1
  python run_batch.py --agent openai --model gpt-4o --no-reset
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable

DEFAULT_BATCH: list[str] = [
    "S-1", "S-2", "S-3", "S-4", "S-5", "S-6",
    "I-1", "I-2", "I-3", "I-4", "I-5", "I-6",
]

RESET_SCRIPT = REPO_ROOT / "potential_scripts" / "reset_database.py"
FURNISH_SCRIPT = REPO_ROOT / "scripts" / "furnish_database.py"

# ──────────────────────────────────────────────────────────────────────────────
# Pretty-printing helpers
# ──────────────────────────────────────────────────────────────────────────────

GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
NC = "\033[0m"

def _c(color: str, text: str) -> str:
    return f"{color}{text}{NC}"

def banner(text: str) -> None:
    line = "=" * 60
    print(f"\n{_c(BOLD, line)}")
    print(_c(BOLD, f"  {text}"))
    print(_c(BOLD, line))

def info(text: str) -> None:
    print(_c(CYAN, f"  {text}"))

def ok(text: str) -> None:
    print(_c(GREEN, f"  ✓ {text}"))

def warn(text: str) -> None:
    print(_c(YELLOW, f"  ! {text}"), file=sys.stderr)

def err(text: str) -> None:
    print(_c(RED, f"  ✗ {text}"), file=sys.stderr)

# ──────────────────────────────────────────────────────────────────────────────
# Result tracking
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TaskResult:
    task_id: str
    status: str = "PENDING"      # OK | FAILED | SKIPPED
    reset_ok: bool = True
    furnish_ok: bool = True
    run_ok: bool = True
    error: str = ""
    elapsed: float = 0.0

@dataclass
class BatchSummary:
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    results: list[TaskResult] = field(default_factory=list)
    agent: str = ""
    model: str = ""

    def print(self) -> None:
        banner("Batch Summary")
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == "OK")
        failed = sum(1 for r in self.results if r.status == "FAILED")
        skipped = sum(1 for r in self.results if r.status == "SKIPPED")

        print(f"\n  Agent  : {self.agent} / {self.model}")
        print(f"  Tasks  : {total}  |  "
              f"{_c(GREEN, f'OK: {passed}')}  "
              f"{_c(RED, f'FAILED: {failed}')}  "
              f"{_c(YELLOW, f'SKIPPED: {skipped}')}")
        print()

        col_w = 10
        header = (
            f"  {'Task':<8} {'Status':<10} {'Reset':<8} "
            f"{'Furnish':<10} {'Run':<8} {'Time':>7}  Error"
        )
        print(header)
        print("  " + "-" * 74)

        for r in self.results:
            status_str = (
                _c(GREEN, "OK") if r.status == "OK"
                else _c(RED, "FAILED") if r.status == "FAILED"
                else _c(YELLOW, "SKIPPED")
            )
            reset_str  = _c(GREEN, "ok") if r.reset_ok   else _c(RED, "FAIL")
            furnish_str = _c(GREEN, "ok") if r.furnish_ok else _c(RED, "FAIL")
            run_str    = _c(GREEN, "ok") if r.run_ok     else _c(RED, "FAIL")
            t = f"{r.elapsed:6.1f}s"
            error_short = (r.error[:40] + "…") if len(r.error) > 40 else r.error
            print(f"  {r.task_id:<8} {status_str:<19} {reset_str:<16} "
                  f"{furnish_str:<18} {run_str:<16} {t}  {error_short}")

        total_time = sum(r.elapsed for r in self.results)
        print(f"\n  Total elapsed: {total_time:.1f}s")
        print()

# ──────────────────────────────────────────────────────────────────────────────
# Core steps
# ──────────────────────────────────────────────────────────────────────────────

def reset_database(odoo_args: list[str]) -> None:
    """Cancel/delete all modified records to restore a clean slate."""
    info("Resetting database …")
    subprocess.run(
        [PYTHON, str(RESET_SCRIPT)] + odoo_args,
        check=True,
        cwd=REPO_ROOT,
    )
    ok("Database reset complete.")


def furnish_database(odoo_args: list[str]) -> None:
    """Inject full task dataset + noisy background data into Odoo."""
    info("Furnishing database …")
    result = subprocess.run(
        [PYTHON, str(FURNISH_SCRIPT)] + odoo_args,
        cwd=REPO_ROOT,
    )
    if result.returncode not in (0, 1):
        # furnish_database exits 1 when there are minor data issues; treat as OK.
        # Any other code is a hard failure.
        raise subprocess.CalledProcessError(result.returncode, str(FURNISH_SCRIPT))
    ok("Database furnished.")


def run_task(
    task_id: str,
    agent: str,
    model: str,
    kl: str,
    max_steps: int,
    runs: int,
    extra_harness_args: list[str],
) -> None:
    """Invoke the research harness for a single task."""
    info(f"Running task {task_id} …")
    cmd = [
        PYTHON, "-m", "research.harness", "run",
        "--agent", agent,
        "--model", model,
        "--task-id", task_id,
        "--kl", kl,
        "--max-steps", str(max_steps),
        "--runs", str(runs),
    ] + extra_harness_args
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)
    ok(f"Task {task_id} complete.")


# ──────────────────────────────────────────────────────────────────────────────
# Batch orchestration
# ──────────────────────────────────────────────────────────────────────────────

def run_batch(
    tasks: list[str],
    agent: str,
    model: str,
    kl: str,
    max_steps: int,
    runs: int,
    no_reset: bool,
    odoo_args: list[str],
    extra_harness_args: list[str],
    stop_on_failure: bool,
) -> BatchSummary:
    summary = BatchSummary(agent=agent, model=model)

    banner(f"Halluci-Action Batch Runner  [{len(tasks)} tasks]")
    print(f"  Agent   : {agent} / {model}")
    print(f"  KL      : {kl}")
    print(f"  Tasks   : {', '.join(tasks)}")
    print(f"  Reset   : {'disabled' if no_reset else 'before each task'}")
    print(f"  Runs    : {runs} per task")

    for idx, task_id in enumerate(tasks, 1):
        banner(f"Task {idx}/{len(tasks)}: {task_id}")
        tr = TaskResult(task_id=task_id)
        t0 = time.monotonic()

        # ── Reset ──────────────────────────────────────────────────────────
        if not no_reset:
            try:
                reset_database(odoo_args)
            except Exception as exc:
                err(f"Reset failed: {exc}")
                tr.reset_ok = False
                tr.furnish_ok = False
                tr.run_ok = False
                tr.status = "FAILED"
                tr.error = f"reset: {exc}"
                tr.elapsed = time.monotonic() - t0
                summary.results.append(tr)
                if stop_on_failure:
                    break
                continue

            # ── Furnish ───────────────────────────────────────────────────
            try:
                furnish_database(odoo_args)
            except Exception as exc:
                err(f"Furnish failed: {exc}")
                tr.furnish_ok = False
                tr.run_ok = False
                tr.status = "FAILED"
                tr.error = f"furnish: {exc}"
                tr.elapsed = time.monotonic() - t0
                summary.results.append(tr)
                if stop_on_failure:
                    break
                continue

        # ── Run ────────────────────────────────────────────────────────────
        try:
            run_task(task_id, agent, model, kl, max_steps, runs, extra_harness_args)
            tr.status = "OK"
        except Exception as exc:
            err(f"Task run failed: {exc}")
            tr.run_ok = False
            tr.status = "FAILED"
            tr.error = f"run: {exc}"

        tr.elapsed = time.monotonic() - t0
        summary.results.append(tr)

        if tr.status == "FAILED" and stop_on_failure:
            warn("Stopping batch due to failure (--stop-on-failure).")
            break

    # Mark any tasks that were never reached as SKIPPED
    finished_ids = {r.task_id for r in summary.results}
    for tid in tasks:
        if tid not in finished_ids:
            summary.results.append(TaskResult(task_id=tid, status="SKIPPED"))

    return summary


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run a batch of Halluci-Action tasks with DB reset+furnish between each.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Agent settings
    p.add_argument("--agent", default="openai",
                   help="Provider: openai | anthropic | deepseek | qwen | kimi (default: openai)")
    p.add_argument("--model", default="gpt-4o",
                   help="Model name for the chosen provider (default: gpt-4o)")
    p.add_argument("--kl", default="KL1", choices=["KL1", "KL2", "KL3"],
                   help="Knowledge level (default: KL1)")
    p.add_argument("--max-steps", type=int, default=15,
                   help="Max conversation steps per task (default: 15)")
    p.add_argument("--runs", type=int, default=1,
                   help="Number of runs per task (default: 1)")

    # Task selection
    p.add_argument("--tasks", nargs="+", default=None,
                   metavar="TASK_ID",
                   help=f"Task IDs to run (default: {' '.join(DEFAULT_BATCH)})")

    # DB / reset
    p.add_argument("--no-reset", action="store_true",
                   help="Skip database reset/furnish before each task")
    p.add_argument("--odoo-url", default=None)
    p.add_argument("--odoo-db", default=None)
    p.add_argument("--odoo-user", default=None)
    p.add_argument("--odoo-password", default=None)

    # Harness passthrough
    p.add_argument("--api-key", default=None,
                   help="Override provider API key (passed to harness)")
    p.add_argument("--base-url", default=None,
                   help="Override OpenAI-compatible base URL (passed to harness)")
    p.add_argument("--temperature", type=float, default=None,
                   help="Sampling temperature (passed to harness)")

    p.add_argument("--stop-on-failure", action="store_true",
                   help="Abort the batch on the first task failure")

    return p.parse_args()


def build_odoo_args(args: argparse.Namespace) -> list[str]:
    """Build CLI args for reset_database.py / furnish_database.py."""
    out: list[str] = []
    if args.odoo_url:
        out += ["--url", args.odoo_url]
    if args.odoo_db:
        out += ["--db", args.odoo_db]
    if args.odoo_user:
        out += ["--user", args.odoo_user]
    if args.odoo_password:
        out += ["--password", args.odoo_password]
    return out


def build_extra_harness_args(args: argparse.Namespace) -> list[str]:
    """Build extra CLI args forwarded to the harness."""
    out: list[str] = []
    if args.api_key:
        out += ["--api-key", args.api_key]
    if args.base_url:
        out += ["--base-url", args.base_url]
    if args.temperature is not None:
        out += ["--temperature", str(args.temperature)]
    if args.odoo_url:
        out += ["--odoo-url", args.odoo_url]
    if args.odoo_db:
        out += ["--odoo-db", args.odoo_db]
    if args.odoo_user:
        out += ["--odoo-user", args.odoo_user]
    if args.odoo_password:
        out += ["--odoo-password", args.odoo_password]
    return out


def main() -> None:
    args = parse_args()

    tasks = args.tasks or DEFAULT_BATCH
    odoo_args = build_odoo_args(args)
    extra_harness_args = build_extra_harness_args(args)

    summary = run_batch(
        tasks=tasks,
        agent=args.agent,
        model=args.model,
        kl=args.kl,
        max_steps=args.max_steps,
        runs=args.runs,
        no_reset=args.no_reset,
        odoo_args=odoo_args,
        extra_harness_args=extra_harness_args,
        stop_on_failure=args.stop_on_failure,
    )

    summary.print()

    failed = sum(1 for r in summary.results if r.status == "FAILED")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
