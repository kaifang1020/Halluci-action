#!/usr/bin/env python3
"""
Batch runner for Gemini 3.1 Flash across task scenarios.

Usage:
    python3 research/run_batch_gemini_flash.py \\
        --model gemini-exp-1114 \\
        --tasks-file task_list.txt \\
        --output-dir research/experiments_v2 \\
        --runs 1
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Map task ID to domain for output organization
TASK_TO_DOMAIN = {
    # Accounting
    **{f"A-{i}": "accounting" for i in range(1, 7)},
    # CRM
    **{f"C-{i}": "crm" for i in range(1, 7)},
    # Helpdesk
    **{f"D-{i}": "helpdesk" for i in range(1, 7)},
    # HR
    **{f"H-{i}": "hr" for i in range(1, 7)},
    # Inventory
    **{f"I-{i}": "inventory" for i in range(1, 7)},
    # Manufacturing
    **{f"M-{i}": "manufacturing" for i in range(1, 7)},
    # POS
    **{f"P-{i}": "pos" for i in range(1, 7)},
    # Project
    **{f"PR-{i}": "project" for i in range(1, 7)},
    # Purchase
    **{f"PU-{i}": "purchase" for i in range(1, 7)},
    # Sales
    **{f"S-{i}": "sales" for i in range(1, 12) if i in [1,2,3,4,5,6,9,10,11]},
}


def get_all_tasks() -> list[str]:
    """Get all task IDs from TASK_TO_DOMAIN mapping."""
    return sorted(TASK_TO_DOMAIN.keys())


def run_task(
    task_id: str,
    model: str,
    output_dir: Path,
    runs: int = 1,
    api_key: Optional[str] = None,
    **kwargs,
) -> bool:
    """Run a single task with Gemini Flash."""
    domain = TASK_TO_DOMAIN.get(task_id, "unknown")

    # Create output directory structure
    traj_dir = output_dir / "independent" / domain / "trajectories"
    traj_dir.mkdir(parents=True, exist_ok=True)

    # Construct the run command
    cmd = [
        "python3", "-m", "research.harness", "run",
        "--agent", "gemini",
        "--model", model,
        "--task-id", task_id,
        "--runs", str(runs),
        "--runs-dir", str(traj_dir.parent.parent),
    ]

    if api_key:
        cmd.extend(["--api-key", api_key])

    print(f"[{task_id}] Running with {model}...")
    result = subprocess.run(cmd, cwd=Path(__file__).parent)

    if result.returncode != 0:
        print(f"  ✗ FAILED")
        return False
    print(f"  ✓ OK")
    return True


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--model",
        default="@vertexai-hs3645/gemini-3.1-flash-lite-preview",
        help="Gemini model ID (default: gemini-3.1-flash-lite-preview via Portkey)",
    )
    parser.add_argument(
        "--tasks",
        default=None,
        help="Comma-separated task IDs (default: all tasks)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("research/experiments_v2"),
        help="Output directory for results",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of runs per task",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Override GOOGLE_API_KEY",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print tasks to run without executing",
    )

    args = parser.parse_args()

    # Determine which tasks to run
    if args.tasks:
        tasks = [t.strip().upper() for t in args.tasks.split(",")]
    else:
        tasks = get_all_tasks()

    print(f"Will run {len(tasks)} task(s) with {args.model}")
    print(f"  Tasks: {', '.join(tasks[:5])}{'...' if len(tasks) > 5 else ''}")
    print(f"  Runs per task: {args.runs}")
    print(f"  Output dir: {args.output_dir}")
    print()

    if args.dry_run:
        print("[DRY RUN] Task list:")
        for i, task_id in enumerate(tasks, 1):
            domain = TASK_TO_DOMAIN.get(task_id, "?")
            print(f"  {i:2d}. {task_id}  ({domain})")
        return 0

    # Run all tasks
    passed = 0
    failed = 0
    for i, task_id in enumerate(tasks, 1):
        try:
            ok = run_task(
                task_id,
                args.model,
                args.output_dir,
                args.runs,
                args.api_key,
            )
            if ok:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            failed += 1

        print(f"  [{i}/{len(tasks)}] Progress: {passed} passed, {failed} failed")
        print()

    print("=" * 60)
    print(f"FINAL: {passed}/{len(tasks)} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
