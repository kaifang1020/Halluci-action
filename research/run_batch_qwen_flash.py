#!/usr/bin/env python3
"""
Batch runner for Qwen3.6-flash (DashScope alias ``qwen-flash``) over the v2
benchmark.

Unlike ``run_batch_gemini_flash.py`` (which only emits independent
trajectories), this wraps the canonical orchestrator
``scripts/run_experiments_v1.py`` so that:

  * the Postgres/Odoo state is reset + furnished before every independent task
    and once per dependent chain;
  * both ``independent`` and ``dependent`` layouts are produced;
  * output is rerouted to ``research/experiments_v2`` via ``--experiments-dir``.

Resulting layout::

    research/experiments_v2/
      independent/<domain>/{trajectories,audits}/...
      dependent/<domain>/<chain>/{trajectories,audits}/...
      run_summaries/<timestamp>_<mode>_qwen_<model>.jsonl

Usage::

    python3 research/run_batch_qwen_flash.py                 # full sweep (all)
    python3 research/run_batch_qwen_flash.py --mode independent
    python3 research/run_batch_qwen_flash.py --skip-existing # resume
    python3 research/run_batch_qwen_flash.py --dry-run
    python3 research/run_batch_qwen_flash.py --tasks S-1 S-2 --mode independent

Provider config: the DashScope key is read from ``DASHSCOPE_API_KEY`` (set in
``research/.env``); the OpenAI-compatible base URL is resolved by
``research.config`` (``.../compatible-mode/v1``).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT_DIR / "scripts" / "run_experiments_v1.py"
OUTPUT_DIR = ROOT_DIR / "research" / "experiments_v2"

# DashScope alias for the latest Qwen3 flash tier. ``qwen3-flash`` is NOT a
# valid id on the OpenAI-compatible endpoint; ``qwen-flash`` is.
DEFAULT_MODEL = "qwen-flash"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"DashScope model id (default: {DEFAULT_MODEL})")
    parser.add_argument("--mode", choices=["independent", "dependent", "all"],
                        default="all", help="Which layout to produce (default: all)")
    parser.add_argument("--kl", default=os.environ.get("KL", "KL1"))
    parser.add_argument("--runs", type=int, default=int(os.environ.get("RUNS", "1")))
    parser.add_argument("--max-steps", type=int,
                        default=int(os.environ.get("MAX_STEPS", "15")))
    parser.add_argument("--timeout-sec", type=int, default=300)
    parser.add_argument("--tasks", nargs="*",
                        help="Independent task IDs (default: all independent tasks).")
    parser.add_argument("--chains", nargs="*",
                        help="Dependent chain names (default: all chains).")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip tasks whose trajectory already exists.")
    parser.add_argument("--no-codebook", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the run plan without touching the DB or calling the agent.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not os.environ.get("DASHSCOPE_API_KEY"):
        # config.py also reads research/.env, but warn early if neither is set.
        env_file = ROOT_DIR / "research" / ".env"
        has_env_key = env_file.exists() and any(
            line.strip().startswith("DASHSCOPE_API_KEY=") and line.strip() != "DASHSCOPE_API_KEY="
            for line in env_file.read_text(encoding="utf-8").splitlines()
        )
        if not has_env_key:
            print("ERROR: DASHSCOPE_API_KEY is not set (export it or add it to "
                  "research/.env).", file=sys.stderr)
            return 2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        str(ORCHESTRATOR),
        "--agent", "qwen",
        "--model", args.model,
        "--mode", args.mode,
        "--kl", args.kl,
        "--runs", str(args.runs),
        "--max-steps", str(args.max_steps),
        "--timeout-sec", str(args.timeout_sec),
        "--experiments-dir", str(OUTPUT_DIR),
    ]
    if args.tasks:
        command += ["--tasks", *args.tasks]
    if args.chains:
        command += ["--chains", *args.chains]
    if args.skip_existing:
        command.append("--skip-existing")
    if args.no_codebook:
        command.append("--no-codebook")
    if args.dry_run:
        command.append("--dry-run")

    print("=" * 60)
    print("  Halluci-Action — Qwen flash batch (experiments_v2)")
    print("=" * 60)
    print(f"  Model:       qwen / {args.model}")
    print(f"  Mode:        {args.mode}")
    print(f"  KL / runs:   {args.kl} / {args.runs}   max-steps: {args.max_steps}")
    print(f"  Output:      {OUTPUT_DIR}")
    print("=" * 60)
    print("  +", " ".join(command))
    print()

    return subprocess.run(command, cwd=ROOT_DIR).returncode


if __name__ == "__main__":
    sys.exit(main())
