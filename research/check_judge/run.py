"""CLI entry point for check_judge.

Usage::

    python -m research.check_judge.run --stage stage1 \
        --llm-dir   research/eval_v2/stage1/outputs/md \
        --human-dir research/annotations \
        --output    research/check_judge/results/stage1_agreement.json

The CLI discovers the human/LLM file overlap automatically. Files are matched
by their task-id stem: ``D-5_judge_stage1.md`` and ``D-5.md`` both map to
``D-5``. Empty human files are skipped with a note in the output metadata.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib
import json
from collections import defaultdict
from pathlib import Path

from research.check_judge import alignment, classification
from research.check_judge.parsers import parse_annotation_md


def _task_id_from_path(path: Path) -> str:
    return path.stem.split("_")[0]


def _discover_pairs(human_dir: Path, llm_dir: Path) -> tuple[dict[str, Path], dict[str, Path], list[dict]]:
    """Return (human_by_task, llm_by_task, skipped[]) for tasks present in both."""
    human_by_task = {_task_id_from_path(p): p for p in sorted(human_dir.glob("*.md")) if p.is_file()}
    llm_by_task = {_task_id_from_path(p): p for p in sorted(llm_dir.glob("*.md")) if p.is_file()}
    # Drop annotation helper files that aren't task annotations.
    for k in list(human_by_task):
        if k.lower() in {"annotation", "to", "to_check"} or human_by_task[k].name.startswith("annotation_"):
            human_by_task.pop(k)

    skipped: list[dict] = []
    pairs_h: dict[str, Path] = {}
    pairs_l: dict[str, Path] = {}
    for task_id in sorted(set(human_by_task) & set(llm_by_task)):
        h_path = human_by_task[task_id]
        l_path = llm_by_task[task_id]
        if h_path.stat().st_size == 0:
            skipped.append({"task": task_id, "reason": "empty human file"})
            continue
        if l_path.stat().st_size == 0:
            skipped.append({"task": task_id, "reason": "empty llm file"})
            continue
        pairs_h[task_id] = h_path
        pairs_l[task_id] = l_path
    return pairs_h, pairs_l, skipped


def _load_stage_metrics(stage: str) -> list[dict]:
    module = importlib.import_module(f"research.check_judge.stages.{stage}")
    metrics = getattr(module, "METRICS", None)
    if not metrics:
        raise SystemExit(
            f"stages/{stage}.py has empty METRICS — not runnable yet "
            f"(see the file's docstring)."
        )
    return metrics


def _compute_for_pair(
    human_path: Path,
    llm_path: Path,
    metrics: list[dict],
    threshold: float,
    id_bonus: float,
) -> dict:
    human = parse_annotation_md(human_path)
    llm = parse_annotation_md(llm_path)
    aln = alignment.align(
        human["claims"],
        llm["claims"],
        threshold=threshold,
        id_bonus=id_bonus,
    )

    out: dict = {
        "n_human_claims": len(human["claims"]),
        "n_llm_claims": len(llm["claims"]),
        "alignment_params": aln["params"],
        "matched_same_id": sum(1 for m in aln["matched"] if m["same_id"]),
        "matched_diff_id": sum(1 for m in aln["matched"] if not m["same_id"]),
        "unmatched_human_ids": [c["claim_id"] for c in aln["only_human"]],
        "unmatched_llm_ids": [c["claim_id"] for c in aln["only_llm"]],
    }
    for spec in metrics:
        if spec["kind"] == "set":
            out[spec["name"]] = alignment.set_metrics(aln["matched"], aln["only_human"], aln["only_llm"])
        elif spec["kind"] == "classification":
            out[spec["name"]] = classification.pairwise_metrics(
                aln["matched"], spec["field"], spec.get("labels")
            )
        else:
            raise ValueError(f"unknown metric kind: {spec['kind']}")
    return out


def _aggregate_overall(per_task: dict[str, dict], metrics: list[dict]) -> dict:
    """Micro aggregation across tasks.

    - ``set`` metrics: sum TP/FP/FN across tasks, recompute P/R/F1.
    - ``classification`` metrics: concatenate confusion matrices, recompute
      accuracy / macro-F1 / kappa from the merged label sequences.
    """
    overall: dict = {}
    for spec in metrics:
        name = spec["name"]
        if spec["kind"] == "set":
            tp = fp = fn = 0
            for t in per_task.values():
                tp += t[name]["tp"]
                fp += t[name]["fp"]
                fn += t[name]["fn"]
            precision = tp / (tp + fp) if (tp + fp) else 0.0
            recall = tp / (tp + fn) if (tp + fn) else 0.0
            f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
            overall[name] = {
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
            }
        elif spec["kind"] == "classification":
            # Sum confusion matrices to recover the merged pair sequence.
            merged_h: list[str] = []
            merged_l: list[str] = []
            for t in per_task.values():
                cm = t[name].get("confusion", {})
                for h_lbl, row in cm.items():
                    for l_lbl, count in row.items():
                        merged_h.extend([h_lbl] * count)
                        merged_l.extend([l_lbl] * count)
            if not merged_h:
                overall[name] = {"n_evaluated": 0}
                continue
            pseudo_pairs = [
                {"human": {spec["field"]: h}, "llm": {spec["field"]: l}}
                for h, l in zip(merged_h, merged_l)
            ]
            overall[name] = classification.pairwise_metrics(
                pseudo_pairs, spec["field"], spec.get("labels")
            )
    return overall


def main(argv: list[str] | None = None) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    default_llm = repo_root / "research" / "eval_v2" / "stage1" / "outputs" / "md"
    default_human = repo_root / "research" / "annotations"
    default_output = repo_root / "research" / "check_judge" / "results" / "stage1_agreement.json"

    parser = argparse.ArgumentParser(description="check_judge: human vs LLM annotation agreement")
    parser.add_argument("--stage", default="stage1", help="stage config module under stages/")
    parser.add_argument("--llm-dir", type=Path, default=default_llm)
    parser.add_argument("--human-dir", type=Path, default=default_human)
    parser.add_argument("--output", type=Path, default=default_output)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--id-bonus", type=float, default=0.1)
    args = parser.parse_args(argv)

    metrics = _load_stage_metrics(args.stage)
    pairs_h, pairs_l, skipped = _discover_pairs(args.human_dir, args.llm_dir)

    per_task: dict[str, dict] = {}
    for task_id in sorted(pairs_h):
        per_task[task_id] = _compute_for_pair(
            pairs_h[task_id],
            pairs_l[task_id],
            metrics,
            threshold=args.threshold,
            id_bonus=args.id_bonus,
        )

    overall = _aggregate_overall(per_task, metrics)

    report = {
        "stage": args.stage,
        "metadata": {
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "llm_dir": str(args.llm_dir),
            "human_dir": str(args.human_dir),
            "task_ids": list(per_task.keys()),
            "skipped": skipped,
            "alignment_params": {"threshold": args.threshold, "id_bonus": args.id_bonus},
        },
        "per_task": per_task,
        "overall": overall,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {args.output}  ({len(per_task)} tasks, skipped {len(skipped)})")


if __name__ == "__main__":
    main()
