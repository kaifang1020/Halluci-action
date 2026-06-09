"""
Analyze the claim-action gap from Stage-2 verdicts.

A "claim-action gap" is an *action claim* — the agent narrates an intention
(`action_intention`) or a completion (`action_completion`) — that the routed
tool-call / tool-result evidence does NOT support (verdict `not_supported`).
`needs_broader_context` is reported separately: the judge couldn't find the
evidence, which is a routing-coverage signal rather than a confirmed gap.

Reads the enriched verdict rows written by run_stage2.py (each row already
carries claim_type, verdict, reason, evidence_pointer, claim_span, traj_id,
step_id, routed_channels), so no re-join with Stage-1 is needed.

  # default: the gpt-4o results
  python -m research.eval_v3.stage2.analyze_claim_action_gap

  # any results root + custom review-export path
  python -m research.eval_v3.stage2.analyze_claim_action_gap \
      --results-dir research/eval_v3/stage2/binary_results \
      --out research/eval_v3/stage2/claim_action_gap_review.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

ACTION_TYPES = {"action_intention", "action_completion"}
GAP_VERDICT = "not_supported"          # the confirmed claim-action gap
NBC_VERDICT = "needs_broader_context"  # routing-coverage signal


def load_rows(results_dir: Path) -> list[dict]:
    """Read every verdict row under <results_dir>/{dependent,independent}/."""
    rows: list[dict] = []
    for split in ("dependent", "independent"):
        for f in sorted((results_dir / split).glob("*_verdicts.jsonl")):
            stem = f.name.replace("_verdicts.jsonl", "")
            for line in f.open(encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                o = json.loads(line)
                o["_split"] = split
                o["_stem"] = stem
                rows.append(o)
    return rows


def _rate(num: int, den: int) -> str:
    return f"{num/den:.1%}" if den else "—"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results-dir", type=Path,
                   default=HERE / "binary_results_gpt4o",
                   help="Dir with {dependent,independent}/*_verdicts.jsonl "
                        "(default: binary_results_gpt4o).")
    p.add_argument("--out", type=Path, default=None,
                   help="Review-export path (.jsonl). A sibling .csv is also "
                        "written. Default: <results-dir>/../claim_action_gap_review.jsonl")
    args = p.parse_args()

    rows = load_rows(args.results_dir)
    if not rows:
        print(f"No verdict rows under {args.results_dir}. Run Stage-2 first.")
        return

    action = [r for r in rows if r.get("claim_type") in ACTION_TYPES]
    n_all, n_act = len(rows), len(action)
    gaps = [r for r in action if r.get("verdict") == GAP_VERDICT]
    nbc = [r for r in action if r.get("verdict") == NBC_VERDICT]

    print(f"Results: {args.results_dir}")
    print(f"Trajectories: {len({r['_stem'] for r in rows})}   "
          f"claims total: {n_all}   action claims: {n_act}\n")

    # 1) Headline gap rate (action claims only)
    print("=== Claim-action gap (action claims only) ===")
    print(f"  not_supported (gap)       : {len(gaps):>4}  {_rate(len(gaps), n_act)}")
    print(f"  needs_broader_context     : {len(nbc):>4}  {_rate(len(nbc), n_act)}")
    print(f"  supported                 : {n_act-len(gaps)-len(nbc):>4}  "
          f"{_rate(n_act-len(gaps)-len(nbc), n_act)}")

    # 2) By claim_type
    print("\n=== gap rate by action claim_type ===")
    for t in sorted(ACTION_TYPES):
        sub = [r for r in action if r["claim_type"] == t]
        g = sum(1 for r in sub if r["verdict"] == GAP_VERDICT)
        n = sum(1 for r in sub if r["verdict"] == NBC_VERDICT)
        print(f"  {t:<20} N={len(sub):<4} gap={g} ({_rate(g, len(sub))})  "
              f"nbc={n} ({_rate(n, len(sub))})")

    # 3) By split
    print("\n=== gap rate by split ===")
    for split in ("dependent", "independent"):
        sub = [r for r in action if r["_split"] == split]
        g = sum(1 for r in sub if r["verdict"] == GAP_VERDICT)
        print(f"  {split:<12} action_claims={len(sub):<4} gap={g} ({_rate(g, len(sub))})")

    # 4) Per-trajectory (only those with >=1 action claim), sorted by gap rate
    print("\n=== per-trajectory gap rate (action claims) ===")
    by_traj: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in action:
        by_traj[(r["_split"], r["_stem"])].append(r)
    table = []
    for (split, stem), sub in by_traj.items():
        g = sum(1 for r in sub if r["verdict"] == GAP_VERDICT)
        n = sum(1 for r in sub if r["verdict"] == NBC_VERDICT)
        table.append((g / len(sub), split, stem, len(sub), g, n))
    for rate, split, stem, n, g, nb in sorted(table, reverse=True):
        if g or nb:  # only show trajectories with something non-supported
            print(f"  {split:<11}{stem:<28} action={n:<3} gap={g} ({rate:.0%})  nbc={nb}")

    # 5) Review export: every non-supported action claim, exhaustively
    review = [r for r in action if r["verdict"] in (GAP_VERDICT, NBC_VERDICT)]
    out = args.out or (args.results_dir.parent / "claim_action_gap_review.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    cols = ["_split", "_stem", "traj_id", "step_id", "claim_type", "verdict",
            "claim_span", "reason", "evidence_pointer", "routed_channels", "claim_id"]
    with out.open("w", encoding="utf-8") as f:
        for r in review:
            f.write(json.dumps({k: r.get(k) for k in cols}, ensure_ascii=False) + "\n")
    csv_path = out.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in review:
            w.writerow([json.dumps(r.get(k), ensure_ascii=False)
                        if isinstance(r.get(k), (dict, list)) else r.get(k)
                        for k in cols])

    print(f"\nReview export ({len(review)} non-supported action claims, review all):")
    print(f"  {out}")
    print(f"  {csv_path}")

    # 6) Note any parse/api errors so they aren't silently ignored
    errs = Counter(r["verdict"] for r in rows
                   if r.get("verdict") not in
                   {"supported", GAP_VERDICT, NBC_VERDICT})
    if errs:
        print(f"\n[warn] non-verdict rows (excluded from rates): {dict(errs)}")


if __name__ == "__main__":
    main()
