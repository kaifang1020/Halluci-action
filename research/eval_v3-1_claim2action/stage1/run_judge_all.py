"""
Run a Stage 1 judge over all trajectories of one agent model under
`research/experiments_v2/{independent,dependent}` (or a custom layout).

Defaults preserve the original deepseek_chat + experiments_v2/real flow.
Override via CLI for other models:

  # original deepseek_chat run:
  python -m research.eval_v3.stage1.run_judge_all

  # deepseek_reasoner over experiments_v2/{independent,dependent}:
  python -m research.eval_v3.stage1.run_judge_all \\
      --ind-dir experiments_v2/independent \\
      --dep-dir experiments_v2/dependent \\
      --traj-suffix _deepseek_deepseek_reasoner \\
      --output-dir results_deepseek_reasoner
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from research.eval_v3_1_claim2action.stage1.judge import run_judge

BASE = Path(__file__).resolve().parent.parent.parent
SCRIPT_DIR = Path(__file__).parent

PROVIDER = "gemini-pro"
PROMPT_VERSION = "v1"

# r02/r03 reruns are excluded from the independent main set
RERUN_PATTERN = re.compile(r"_r0[2-9]$")


def _collect_independent(ind_dir: Path, traj_suffix: str, results_dir: Path) -> list[tuple[str, Path, Path]]:
    """Returns (output_name, traj_path, out_path) for each independent traj."""
    entries = []
    for traj in sorted(ind_dir.glob(f"*/trajectories/*{traj_suffix}.json")):
        stem = traj.stem.replace(traj_suffix, "")
        if RERUN_PATTERN.search(stem):
            continue
        out_name = f"{stem}_{PROVIDER}_{PROMPT_VERSION}_judge.json"
        entries.append((stem, traj, results_dir / "independent" / out_name))
    return entries


def _collect_dependent(dep_dir: Path, traj_suffix: str, results_dir: Path) -> list[tuple[str, Path, Path]]:
    """Returns (output_name, traj_path, out_path) for each dependent traj."""
    entries = []
    for traj in sorted(dep_dir.glob(f"*/*/trajectories/*{traj_suffix}.json")):
        # path: .../dependent/<domain>/<session_group>/trajectories/<file>.json
        session_group = traj.parent.parent.name   # e.g. C1_C5
        stem = traj.stem.replace(traj_suffix, "")  # e.g. C-1
        out_name = f"{session_group}_{stem}_{PROVIDER}_{PROMPT_VERSION}_judge.json"
        entries.append((f"{session_group}/{stem}", traj, results_dir / "dependent" / out_name))
    return entries


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ind-dir", default="experiments_v2/real/independent",
                   help="Independent trajectory root (relative to research/), default preserves deepseek_chat flow.")
    p.add_argument("--dep-dir", default="experiments_v2/real/dependent",
                   help="Dependent trajectory root (relative to research/), default preserves deepseek_chat flow.")
    p.add_argument("--traj-suffix", default="_deepseek_deepseek_chat",
                   help="Filename suffix to strip from each *.json to produce the task stem.")
    p.add_argument("--output-dir", default="results",
                   help="Output dir name under stage1/ (e.g. results_deepseek_reasoner).")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    ind_dir = BASE / args.ind_dir
    dep_dir = BASE / args.dep_dir
    results_dir = SCRIPT_DIR / args.output_dir

    ind = _collect_independent(ind_dir, args.traj_suffix, results_dir)
    dep = _collect_dependent(dep_dir, args.traj_suffix, results_dir)
    all_entries = [("independent", e) for e in ind] + [("dependent", e) for e in dep]

    total = len(all_entries)
    skipped = 0
    print(f"Ind dir: {ind_dir}")
    print(f"Dep dir: {dep_dir}")
    print(f"Results: {results_dir}")
    print(f"Total trajectories: {total}  ({len(ind)} independent, {len(dep)} dependent)\n")

    for i, (split, (label, traj_path, out_path)) in enumerate(all_entries, 1):
        if out_path.exists():
            print(f"[{i}/{total}] SKIP {split}/{label} (already exists)")
            skipped += 1
            continue

        print(f"[{i}/{total}] {split}/{label} ...", flush=True)
        try:
            steps = run_judge(
                traj_path,
                provider=PROVIDER,
                save_output=out_path,
                prompt_version=PROMPT_VERSION,
            )
            n_claims = sum(len(s.claims) for s in steps)
            print(f"  -> {len(steps)} steps, {n_claims} claims -> {out_path.name}")
        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\nDone. {total - skipped} ran, {skipped} skipped.")


if __name__ == "__main__":
    main()
