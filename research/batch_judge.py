"""
Batch LLM-Judge evaluation for Halluci-Action trajectories.

Runs judge.evaluate_trajectory() in parallel over a set of run files,
prints a live progress bar, and summarises results in a table at the end.

Usage examples
--------------
# Evaluate all new runs (skips already-judged files):
  python -m research.batch_judge \
      --dir research/experiments/runs \
      --judge openai --model gpt-4o

# Dry-run — show which files would be evaluated without calling the API:
  python -m research.batch_judge \
      --dir research/experiments/runs --judge openai --model gpt-4o --dry-run

# Limit to 5 files, 4 parallel workers, auto-match task IDs:
  python -m research.batch_judge \
      --dir research/experiments/runs \
      --judge openai --model gpt-4o \
      --limit 5 --workers 4 --auto-task-id

# Filter by agent (only openai runs):
  python -m research.batch_judge \
      --dir research/experiments/runs \
      --judge openai --model gpt-4o \
      --agent-filter openai

# Re-evaluate everything (ignore existing judge files):
  python -m research.batch_judge \
      --dir research/experiments/runs \
      --judge openai --model gpt-4o --force
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import click
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_trajectories(
    runs_dir: Path,
    pattern: str,
    agent_filter: str | None,
    judge: str,
    model: str,
    force: bool,
    limit: int | None,
) -> list[Path]:
    """Return trajectory files to evaluate, respecting filters."""
    files = sorted(runs_dir.glob(pattern))
    # Never pick up existing judge output files
    files = [f for f in files if "__judge_" not in f.name]

    if agent_filter:
        files = [f for f in files if f"_{agent_filter.lower()}_" in f.name]

    if not force:
        judge_tag = f"__judge_{judge}_{model.replace('/', '-')}"
        out_dir = runs_dir / "evaluations"
        already_done: set[str] = set()
        if out_dir.exists():
            already_done = {p.name for p in out_dir.glob("*__judge_*.json")}
        files = [f for f in files if f"{f.stem}{judge_tag}.json" not in already_done]

    if limit:
        files = files[:limit]

    return files


def _auto_task_id(trajectory: dict[str, Any]) -> str | None:
    """Best-effort: extract a task ID from the trajectory metadata."""
    # Some runs store task_id directly
    tid = trajectory.get("task_id") or trajectory.get("metadata", {}).get("task_id")
    if tid:
        return str(tid)

    # Try to map from user_instruction text — load all task defs and match
    task_text = trajectory.get("task", "")
    if not task_text:
        return None

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tasks_added import TASKS
    except ImportError:
        try:
            from research.tasks import TASKS  # type: ignore[import]
        except ImportError:
            return None

    task_text_lower = task_text.lower().strip()
    best_id: str | None = None
    best_len = 0
    for tid, tdef in TASKS.items():
        instr = tdef.get("user_instruction", "").lower().strip()
        if not instr:
            continue
        # Check longest common prefix match length
        common = sum(1 for a, b in zip(task_text_lower, instr) if a == b)
        if common > best_len:
            best_len = common
            best_id = tid

    # Require at least 30 chars of overlap to count as a match
    return best_id if best_len >= 30 else None


def _evaluate_one(
    path: Path,
    judge: str,
    model: str,
    task_id: str | None,
    auto_task_id: bool,
    api_key: str | None,
    base_url: str | None,
    output_dir: Path | None,
) -> dict[str, Any]:
    """Evaluate a single trajectory; returns a summary dict."""
    from research.judge import evaluate_trajectory

    trajectory = json.loads(path.read_text(encoding="utf-8"))

    resolved_task_id = task_id
    if auto_task_id and not resolved_task_id:
        resolved_task_id = _auto_task_id(trajectory)

    t0 = time.monotonic()
    try:
        result = evaluate_trajectory(
            path,
            judge=judge,
            model=model,
            task_id=resolved_task_id,
            api_key=api_key,
            base_url=base_url,
            output_dir=output_dir,
        )
        elapsed = time.monotonic() - t0
        ev = result.get("evaluation", {})
        return {
            "file": path.name,
            "agent": trajectory.get("agent", "?"),
            "verdict": ev.get("overall_verdict", "?"),
            "faults": len(ev.get("faults", [])),
            "task_id": resolved_task_id,
            "elapsed_s": round(elapsed, 1),
            "error": None,
        }
    except Exception as exc:
        elapsed = time.monotonic() - t0
        return {
            "file": path.name,
            "agent": trajectory.get("agent", "?"),
            "verdict": "ERROR",
            "faults": 0,
            "task_id": resolved_task_id,
            "elapsed_s": round(elapsed, 1),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

_VERDICT_COLOUR = {
    "clean": "green",
    "minor_faults": "yellow",
    "major_faults": "red",
    "ERROR": "bright_red",
}


def _print_summary(rows: list[dict[str, Any]]) -> None:
    click.echo("\n" + "=" * 72)
    click.echo(f"{'FILE':<44} {'AGENT':<10} {'VERDICT':<14} {'FAULTS':>6} {'SEC':>5}")
    click.echo("-" * 72)
    for r in rows:
        colour = _VERDICT_COLOUR.get(r["verdict"], "white")
        verdict_str = click.style(f"{r['verdict']:<14}", fg=colour)
        fname = r["file"]
        if len(fname) > 43:
            fname = "…" + fname[-42:]
        click.echo(
            f"{fname:<44} {r['agent']:<10} {verdict_str} {r['faults']:>6} {r['elapsed_s']:>5}"
        )
        if r["error"]:
            click.echo(f"  {'':>44} ERROR: {r['error'][:60]}")

    click.echo("=" * 72)
    total = len(rows)
    errors = sum(1 for r in rows if r["error"])
    clean = sum(1 for r in rows if r["verdict"] == "clean")
    minor = sum(1 for r in rows if r["verdict"] == "minor_faults")
    major = sum(1 for r in rows if r["verdict"] == "major_faults")
    click.echo(
        f"Total: {total}  |  "
        + click.style(f"clean: {clean}", fg="green") + "  "
        + click.style(f"minor: {minor}", fg="yellow") + "  "
        + click.style(f"major: {major}", fg="red") + "  "
        + click.style(f"errors: {errors}", fg="bright_red" if errors else "white")
    )

    # Save summary JSON alongside the evaluations
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command("batch-judge")
@click.option("--dir", "runs_dir", required=True, type=click.Path(exists=True),
              help="Directory containing trajectory JSON files")
@click.option("--judge", required=True,
              type=click.Choice(
                  ["openai", "anthropic", "deepseek", "gemini", "gemini-compat", "custom"],
                  case_sensitive=False,
              ))
@click.option("--model", required=True, help="Judge model name")
@click.option("--task-id", default=None,
              help="Apply this task ID to every trajectory (overrides --auto-task-id)")
@click.option("--auto-task-id", is_flag=True, default=False,
              help="Auto-match task IDs from tasks_added.py by instruction text")
@click.option("--api-key", default=None, help="Override API key")
@click.option("--base-url", default=None, help="Override base URL")
@click.option("--output-dir", default=None, type=click.Path(),
              help="Where to save evaluation JSONs (default: <runs_dir>/evaluations/)")
@click.option("--workers", default=4, show_default=True,
              help="Number of parallel judge threads")
@click.option("--limit", default=None, type=int,
              help="Max number of files to evaluate (for quick tests)")
@click.option("--agent-filter", default=None,
              help="Only evaluate runs from this agent provider (e.g. openai, deepseek)")
@click.option("--pattern", default="*.json", show_default=True,
              help="Glob pattern for trajectory files")
@click.option("--force", is_flag=True, default=False,
              help="Re-evaluate even if a judge file already exists")
@click.option("--dry-run", is_flag=True, default=False,
              help="List files that would be evaluated, then exit")
@click.option("--save-summary", is_flag=True, default=False,
              help="Save a batch_summary.json to the output dir after evaluation")
def batch_judge(
    runs_dir: str,
    judge: str,
    model: str,
    task_id: str | None,
    auto_task_id: bool,
    api_key: str | None,
    base_url: str | None,
    output_dir: str | None,
    workers: int,
    limit: int | None,
    agent_filter: str | None,
    pattern: str,
    force: bool,
    dry_run: bool,
    save_summary: bool,
) -> None:
    """Batch-evaluate trajectory files with an LLM judge (parallel)."""
    runs_path = Path(runs_dir)
    out_path = Path(output_dir) if output_dir else runs_path / "evaluations"

    files = _find_trajectories(
        runs_path, pattern, agent_filter, judge, model, force, limit
    )

    if not files:
        click.echo("No trajectory files to evaluate (all already done, or dir is empty).")
        click.echo("Use --force to re-evaluate or --dir to specify a different directory.")
        return

    click.echo(
        f"Found {len(files)} file(s) to evaluate  |  "
        f"judge={judge}/{model}  workers={workers}"
    )

    if dry_run:
        click.echo("\n[dry-run] Would evaluate:")
        for f in files:
            click.echo(f"  {f.name}")
        return

    rows: list[dict[str, Any]] = []
    completed = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _evaluate_one,
                path=f,
                judge=judge,
                model=model,
                task_id=task_id,
                auto_task_id=auto_task_id,
                api_key=api_key,
                base_url=base_url,
                output_dir=out_path,
            ): f
            for f in files
        }

        for future in as_completed(futures):
            completed += 1
            result = future.result()
            rows.append(result)
            verdict_str = click.style(result["verdict"], fg=_VERDICT_COLOUR.get(result["verdict"], "white"))
            status = f"[{completed}/{len(files)}] {result['file'][:50]}  →  {verdict_str}"
            if result["error"]:
                status += f"  ERROR: {result['error'][:50]}"
            click.echo(status)

    # Sort rows to match original file order
    file_order = {f.name: i for i, f in enumerate(files)}
    rows.sort(key=lambda r: file_order.get(r["file"], 999))

    _print_summary(rows)

    if save_summary:
        out_path.mkdir(parents=True, exist_ok=True)
        summary_path = out_path / f"batch_summary_{judge}_{model.replace('/', '-')}.json"
        summary_path.write_text(
            json.dumps({"judge": judge, "model": model, "results": rows}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        click.echo(f"\nSummary saved → {summary_path}")


if __name__ == "__main__":
    batch_judge()
