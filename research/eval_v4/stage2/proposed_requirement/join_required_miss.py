#!/usr/bin/env python3
"""Join the requirement-judge output for the not_supported action claims back to
the per-model over-claim counts, to split ① over-claims into:

  required_miss        = required ∧ not_supported   (claimed a task-REQUIRED action,
                                                      no evidence it was done — high risk)
  forbidden over-claim = forbidden ∧ not_supported  (claimed a prohibited action)
  benign over-claim    = allowed_supporting / unnecessary / unclear ∧ not_supported

Outputs a per-model table and saves it to human_review/required_miss_table.json.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
STAGE2 = HERE.parents[2] / "eval_v3-1_claim2action" / "stage2"

# L (action claims) per model — micro denominators (independent + dependent).
def action_claim_L() -> dict[str, int]:
    L = collections.Counter()
    for it in (json.loads(l) for l in (OUT / "all_claim_items.jsonl").read_text().splitlines() if l.strip()):
        L[it["author_model"]] += 1
    return dict(L)


def main() -> None:
    items = {it["item_id"]: it for it in
             (json.loads(l) for l in (OUT / "not_supported_items.jsonl").read_text().splitlines() if l.strip())}
    preds = [json.loads(l) for l in
             (OUT / "not_supported_requirement_predictions.jsonl").read_text().splitlines() if l.strip()]
    L = action_claim_L()

    # per model: status counts among not_supported action claims
    by = collections.defaultdict(collections.Counter)
    for p in preds:
        it = items.get(p["item_id"])
        if not it:
            continue
        by[it["author_model"]][p.get("requirement_status")] += 1

    models = ["deepseek_chat", "deepseek_reasoner", "gemini_flash", "gpt4o_mini", "qwen"]
    rows = []
    print(f"{'model':18}{'L':>6}{'overclaim(Lns)':>15}{'required_miss':>14}{'forbidden':>10}{'benign':>8}"
          f"{'  ①rate':>8}{'  req_miss/L':>12}")
    print("-" * 95)
    for m in models:
        c = by.get(m, collections.Counter())
        lns = sum(c.values())
        req_miss = c.get("required", 0)
        forb = c.get("forbidden", 0)
        benign = c.get("allowed_supporting", 0) + c.get("unnecessary", 0) + c.get("unclear", 0)
        Lm = L.get(m, 0)
        over_rate = lns / Lm if Lm else 0
        rm_rate = req_miss / Lm if Lm else 0
        rows.append({"model": m, "L": Lm, "overclaim_Lns": lns, "required_miss": req_miss,
                     "forbidden_overclaim": forb, "benign_overclaim": benign,
                     "overclaim_rate": over_rate, "required_miss_rate": rm_rate,
                     "status_breakdown": dict(c)})
        print(f"{m:18}{Lm:>6}{lns:>15}{req_miss:>14}{forb:>10}{benign:>8}"
              f"{over_rate*100:>7.1f}%{rm_rate*100:>11.2f}%")
    (STAGE2 / "human_review" / "required_miss_table.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8")
    print("\nsaved -> binary_results.../human_review/required_miss_table.json")


if __name__ == "__main__":
    main()
