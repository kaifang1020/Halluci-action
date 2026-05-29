"""
Run Gemini Pro v1 Stage 1 judge on all independent and dependent trajectories.

  python -m research.eval_v3.stage1.run_judge_all
"""
from __future__ import annotations

import re
from pathlib import Path

from research.eval_v3.stage1.judge import run_judge

BASE = Path(__file__).resolve().parent.parent.parent
RESULTS = Path(__file__).parent / "results"
IND_DIR = BASE / "experiments_v2/real/independent"
DEP_DIR = BASE / "experiments_v2/real/dependent"

PROVIDER = "gemini-pro"
PROMPT_VERSION = "v1"

# r02/r03 reruns are excluded from the independent main set
RERUN_PATTERN = re.compile(r"_r0[2-9]$")


def _collect_independent() -> list[tuple[str, Path, Path]]:
    """Returns (output_name, traj_path, out_path) for each independent traj."""
    entries = []
    for traj in sorted(IND_DIR.glob("*/trajectories/*.json")):
        stem = traj.stem.replace("_deepseek_deepseek_chat", "")
        if RERUN_PATTERN.search(stem):
            continue
        out_name = f"{stem}_gemini-pro_v1_judge.json"
        entries.append((stem, traj, RESULTS / "independent" / out_name))
    return entries


def _collect_dependent() -> list[tuple[str, Path, Path]]:
    """Returns (output_name, traj_path, out_path) for each dependent traj."""
    entries = []
    for traj in sorted(DEP_DIR.glob("*/*/trajectories/*.json")):
        # path: .../dependent/<domain>/<session_group>/trajectories/<file>.json
        session_group = traj.parent.parent.name   # e.g. C1_C5
        stem = traj.stem.replace("_deepseek_deepseek_chat", "")  # e.g. C-1
        out_name = f"{session_group}_{stem}_gemini-pro_v1_judge.json"
        entries.append((f"{session_group}/{stem}", traj, RESULTS / "dependent" / out_name))
    return entries


def main() -> None:
    ind = _collect_independent()
    dep = _collect_dependent()
    all_entries = [("independent", e) for e in ind] + [("dependent", e) for e in dep]

    total = len(all_entries)
    skipped = 0
    print(f"Total trajectories: {total}  ({len(ind)} independent, {len(dep)} dependent)")

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
