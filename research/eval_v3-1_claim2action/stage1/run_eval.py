"""
Stage 1 judge evaluation.

Usage:
  # Run judge + evaluate (calls API):
  python -m research.eval_v3.stage1.run_eval

  # Skip API call, load cached judge output:
  python -m research.eval_v3.stage1.run_eval --cached

  # Run on a single traj (by annotation id):
  python -m research.eval_v3.stage1.run_eval --id C-1_deepseek
"""
from __future__ import annotations

import argparse
from pathlib import Path

from research.eval_v3.stage1.evaluate import TrajResult, evaluate_traj
from research.eval_v3.stage1.judge import load_judge_output, run_judge
from research.eval_v3.stage1.parse_gold import parse_gold_annotation

BASE = Path(__file__).resolve().parent.parent.parent

ANNOTATIONS_DIR = BASE / "annotations" / "v2"
OUTPUTS_DIR = Path(__file__).parent / "outputs"

EVAL_SET: dict[str, Path] = {
    "C-1_deepseek": BASE / "experiments_v2/real/independent/crm/trajectories/C-1_deepseek_deepseek_chat.json",
    "D-5_deepseek_r02": BASE / "experiments_v2/real/independent/helpdesk/trajectories/D-5_deepseek_deepseek_chat_r02.json",
    "PR-2_deepseek": BASE / "experiments_v2/real/independent/project/trajectories/PR-2_deepseek_deepseek_chat.json",
}


def _print_report(results: list[TrajResult]) -> None:
    print("\n" + "=" * 62)
    print("STAGE 1 EVALUATION REPORT")
    print("=" * 62)

    for tr in results:
        print(f"\nTraj: {tr.traj_id}")
        print(f"  Traj  P={tr.precision:.3f}  R={tr.recall:.3f}  F1={tr.f1:.3f}")
        for sr in tr.steps:
            n_gold = sum(1 for c in sr.claims if c.gold_span is not None)
            n_judge = sum(1 for c in sr.claims if c.judge_span is not None)
            n_matched = sum(1 for c in sr.claims if c.gold_span and c.judge_span)
            print(
                f"    Step {sr.step_id:2d}: P={sr.precision:.3f}  R={sr.recall:.3f}"
                f"  gold={n_gold}  judge={n_judge}  matched={n_matched}"
            )

    # Macro-average over trajs
    avg_p = sum(t.precision for t in results) / len(results)
    avg_r = sum(t.recall for t in results) / len(results)
    avg_f1 = sum(t.f1 for t in results) / len(results)

    print(f"\nMacro-avg over {len(results)} trajs:")
    print(f"  P={avg_p:.3f}  R={avg_r:.3f}  F1={avg_f1:.3f}")
    print("=" * 62)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cached", action="store_true", help="Load cached judge outputs instead of calling API")
    parser.add_argument("--id", default=None, help="Run only this annotation id")
    parser.add_argument("--provider", default="deepseek", help="Judge provider: deepseek | gemini-pro | gemini-flash")
    parser.add_argument("--prompt-version", default=None, dest="prompt_version",
                        help="Prompt version suffix, e.g. v1 → uses system_v1.md and fewshot_v1.md")
    args = parser.parse_args()

    target_ids = [args.id] if args.id else list(EVAL_SET.keys())

    pv = args.prompt_version
    suffix = f"_{pv}" if pv else ""

    results: list[TrajResult] = []

    for ann_id in target_ids:
        traj_path = EVAL_SET[ann_id]
        ann_path = ANNOTATIONS_DIR / f"{ann_id}.md"
        output_path = OUTPUTS_DIR / f"{ann_id}_{args.provider}{suffix}_judge.json"

        print(f"\n[{ann_id}] provider={args.provider} prompt={pv or 'default'}")

        if args.cached:
            if not output_path.exists():
                print(f"  No cached output found at {output_path}, skipping.")
                continue
            print(f"  Loading cached output from {output_path}")
            judge_steps = load_judge_output(output_path)
        else:
            print(f"  Running judge on {traj_path.name} ...")
            judge_steps = run_judge(traj_path, provider=args.provider, save_output=output_path,
                                    prompt_version=pv)
            print(f"  Saved judge output to {output_path}")

        gold = parse_gold_annotation(ann_path)
        traj_result = evaluate_traj(gold, judge_steps)
        results.append(traj_result)

        eval_output = OUTPUTS_DIR / f"{ann_id}_{args.provider}{suffix}_eval.json"
        eval_output.write_text(
            __import__("json").dumps(traj_result.to_dict(), indent=2, ensure_ascii=False)
        )
        print(f"  P={traj_result.precision:.3f}  R={traj_result.recall:.3f}  F1={traj_result.f1:.3f}")
        print(f"  Saved eval results to {eval_output}")

    if results:
        _print_report(results)


if __name__ == "__main__":
    main()
