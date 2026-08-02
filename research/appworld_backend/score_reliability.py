"""Judge-reliability report for the AppWorld pipeline.

Two kinds of agreement, both via check_judge_appworld.pairwise_metrics (accuracy,
macro-F1, Cohen's kappa, per-class P/R/F1):

  * judge-vs-judge  (no human needed): do deepseek and qwen-plus agree on the SAME
    item? High kappa = the label is stable across judge backends; the disagreements
    are the hard cases worth human eyes.
  * judge-vs-human  (needs filled worksheets): the real reliability number, per judge
    model — how often each judge matches the human gold label.

Consumes the pools from gen_validation_data.py:
    runs/validation/pool_fidelity.jsonl   (claim_id, judge_model, verdict)
    runs/validation/pool_action.jsonl     (action_id, judge_model, said, requirement_status)
and, when available, the filled worksheets:
    *.labels.jsonl  with {item_id, human_verdict | human_said | human_requirement_status}

Usage:
    # preview (judge-vs-judge only)
    python score_reliability.py
    # full (adds judge-vs-human)
    python score_reliability.py --labels runs/validation/*.labels.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
from collections import defaultdict
from pathlib import Path

from check_judge_appworld import pairwise_metrics

BASE = Path(__file__).resolve().parent
VAL = BASE / "runs" / "validation"

FIELDS = {  # label field -> (pool file, id key, judge column, label universe)
    # claim_id is globally unique; action_id ("step1_action0") is NOT — it repeats
    # across trajectories, so actions join on a composite uid (== the worksheet item_id).
    "fidelity": ("pool_fidelity.jsonl", "claim_id", "verdict",
                 ["supported", "not_supported"]),
    "said": ("pool_action.jsonl", "uid", "said",
             ["true", "false"]),
    "requirement_status": ("pool_action.jsonl", "uid", "requirement_status",
                           ["required", "allowed_supporting", "unnecessary", "forbidden"]),
}


def _add_uid(rows: list[dict]) -> list[dict]:
    """Composite action id matching make_worksheet's item_id: task__agent::action_id."""
    for r in rows:
        r["uid"] = f'{r.get("task_id")}__{r.get("agent_model")}::{r.get("action_id")}'
    return rows


def _load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


_INVALID = {"parse_error", "api_error", "error", "needs_broader_context"}  # judge failed/abstained → not a label


def _norm(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    return None if s in _INVALID else s


def _pivot(rows: list[dict], id_key: str, field: str) -> dict[str, dict[str, str]]:
    """item_id -> {judge_model: label}."""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for r in rows:
        iid = r.get(id_key)
        if iid is None:
            continue
        out[iid][str(r.get("judge_model"))] = _norm(r.get(field))
    return out


def judge_vs_judge(rows: list[dict], id_key: str, field: str, labels: list[str]) -> dict:
    piv = _pivot(rows, id_key, field)
    models = sorted({m for v in piv.values() for m in v})
    result = {"judge_models": models, "n_items": len(piv), "pairs": {}}
    for i in range(len(models)):
        for j in range(i + 1, len(models)):
            a, b = models[i], models[j]
            pairs = [{"human": {"x": v[a]}, "llm": {"x": v[b]}}
                     for v in piv.values() if v.get(a) and v.get(b)]
            m = pairwise_metrics(pairs, "x", labels=labels)
            disagree = [iid for iid, v in piv.items()
                        if v.get(a) and v.get(b) and v[a] != v[b]]
            result["pairs"][f"{a}__vs__{b}"] = {
                "accuracy": m["accuracy"], "cohen_kappa": m["cohen_kappa"],
                "n": m["n_evaluated"], "n_disagree": len(disagree),
                "disagreements": disagree[:30],
            }
    return result


def judge_vs_human(rows: list[dict], gold: dict[str, str], id_key: str,
                   field: str, labels: list[str]) -> dict:
    piv = _pivot(rows, id_key, field)
    models = sorted({m for v in piv.values() for m in v})
    result = {"judge_models": models, "n_gold": len(gold), "per_model": {}}
    for mdl in models:
        pairs = [{"human": {"x": gold[iid]}, "llm": {"x": v[mdl]}}
                 for iid, v in piv.items() if iid in gold and v.get(mdl)]
        result["per_model"][mdl] = pairwise_metrics(pairs, "x", labels=labels)
    return result


def collect_gold(label_paths: list[Path]) -> dict[str, dict[str, str]]:
    """field -> {item_id -> human label}. Reads human_<field> keys from worksheets."""
    gold: dict[str, dict[str, str]] = {"fidelity": {}, "said": {}, "requirement_status": {}}
    keymap = {"human_verdict": "fidelity", "human_said": "said",
              "human_requirement_status": "requirement_status"}
    for p in label_paths:
        for r in _load_jsonl(p):
            iid = r.get("item_id")
            for hk, field in keymap.items():
                v = _norm(r.get(hk))
                if iid and v is not None:
                    gold[field][iid] = v
    return gold


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--labels", nargs="*", default=[], help="filled *.labels.jsonl (globs ok)")
    p.add_argument("--out", type=Path, default=VAL / "reliability_report.json")
    args = p.parse_args()

    pools = {}
    for name, (fn, id_key, *_ ) in FIELDS.items():
        rows = _load_jsonl(VAL / fn)
        if id_key == "uid":
            _add_uid(rows)
        pools[name] = rows
    report: dict = {"judge_vs_judge": {}, "judge_vs_human": {}}

    print("=== JUDGE vs JUDGE (no human; disagreements = hard cases) ===")
    for field, (fn, id_key, col, labels) in FIELDS.items():
        rows = pools[field]
        jj = judge_vs_judge(rows, id_key, col, labels)
        report["judge_vs_judge"][field] = jj
        for pairname, s in jj["pairs"].items():
            print(f"  {field:20s} {pairname:26s} acc={s['accuracy']} κ={s['cohen_kappa']} "
                  f"(n={s['n']}, disagree={s['n_disagree']})")

    gold_paths = [Path(x) for g in args.labels for x in glob.glob(g)]
    if gold_paths:
        gold = collect_gold(gold_paths)
        print("\n=== JUDGE vs HUMAN (reliability) ===")
        for field, (fn, id_key, col, labels) in FIELDS.items():
            g = gold.get(field, {})
            if not g:
                print(f"  {field:20s} (no human labels yet)")
                continue
            jh = judge_vs_human(pools[field], g, id_key, col, labels)
            report["judge_vs_human"][field] = jh
            for mdl, m in jh["per_model"].items():
                print(f"  {field:20s} {mdl:12s} acc={m['accuracy']} κ={m['cohen_kappa']} "
                      f"macroF1={m['macro_f1']} (n={m['n_evaluated']})")
    else:
        print("\n(no --labels: skipping judge-vs-human. Fill label_worksheet.html then pass *.labels.jsonl)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
