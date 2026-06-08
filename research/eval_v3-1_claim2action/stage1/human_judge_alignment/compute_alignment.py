"""
Stage 1 alignment: measure how well the judge's atomic claim extraction
matches human gold annotations.

Metrics (all at claim level, not word level):
  span_recall    = |matched| / |gold|       # how many gold claims did judge find?
  span_precision = |matched| / |judge|      # of judge's claims, how many are valid?
  type_accuracy  = |type_correct| / |matched|  # among matched, how often is type right?

Matching rule: greedy bipartite matching maximising token overlap;
  a pair is "matched" iff overlap >= MATCH_THRESHOLD (default 0.80).

Usage:
  python -m research.eval_v3-1_claim2action.stage1.human_judge_alignment.compute_alignment
  python -m research.eval_v3-1_claim2action.stage1.human_judge_alignment.compute_alignment \\
      --traj C-1_deepseek --verbose
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent   # research/
GOLD_DIR = BASE / "annotations" / "v2" / "stage1"
JUDGE_DIR = BASE / "eval_v3-1_claim2action" / "stage1" / "results_deepseek_chat" / "independent"

sys.path.insert(0, str(BASE / "eval_v3-1_claim2action"))
from stage1.parse_gold import GoldAnnotation, GoldClaim, parse_gold_annotation

MATCH_THRESHOLD = 0.80  # minimum token overlap fraction to count as a match


# ── Tokenisation ──────────────────────────────────────────────────────────────

def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _token_overlap(a: str, b: str) -> float:
    """Fraction of shorter span's tokens that also appear in the longer span."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    ca = Counter(ta)
    cb = Counter(tb)
    inter = sum((ca & cb).values())
    return inter / min(len(ta), len(tb))


# ── Per-step matching ─────────────────────────────────────────────────────────

@dataclass
class ClaimPair:
    gold_id: str | None
    gold_span: str | None
    gold_type: str | None
    judge_span: str | None
    judge_type: str | None
    overlap: float        # 0.0 for unmatched
    matched: bool         # overlap >= threshold
    type_correct: bool | None  # None if unmatched on either side


@dataclass
class StepAlignment:
    step_id: int
    n_gold: int
    n_judge: int
    pairs: list[ClaimPair]

    @property
    def n_matched(self) -> int:
        return sum(1 for p in self.pairs if p.matched)

    @property
    def n_type_correct(self) -> int:
        return sum(1 for p in self.pairs if p.type_correct is True)

    @property
    def span_recall(self) -> float:
        return self.n_matched / self.n_gold if self.n_gold else 1.0

    @property
    def span_precision(self) -> float:
        return self.n_matched / self.n_judge if self.n_judge else 1.0

    @property
    def type_accuracy(self) -> float:
        return self.n_type_correct / self.n_matched if self.n_matched else 0.0


def align_step(
    step_id: int,
    gold_claims: list[GoldClaim],
    judge_claims: list[dict],
    threshold: float = MATCH_THRESHOLD,
) -> StepAlignment:
    """Greedy bipartite matching on token overlap."""
    # Build all pairwise scores
    scores = [
        (i, j, _token_overlap(g.span, jc["span"]))
        for i, g in enumerate(gold_claims)
        for j, jc in enumerate(judge_claims)
    ]
    scores.sort(key=lambda x: -x[2])

    matched_g: set[int] = set()
    matched_j: set[int] = set()
    pairs: list[ClaimPair] = []

    for i, j, ov in scores:
        if ov < threshold:
            break
        if i in matched_g or j in matched_j:
            continue
        g = gold_claims[i]
        jc = judge_claims[j]
        pairs.append(ClaimPair(
            gold_id=g.claim_id,
            gold_span=g.span,
            gold_type=g.type,
            judge_span=jc["span"],
            judge_type=jc["type"],
            overlap=ov,
            matched=True,
            type_correct=(g.type == jc["type"]),
        ))
        matched_g.add(i)
        matched_j.add(j)

    # Unmatched gold → false negatives
    for i, g in enumerate(gold_claims):
        if i not in matched_g:
            pairs.append(ClaimPair(
                gold_id=g.claim_id, gold_span=g.span, gold_type=g.type,
                judge_span=None, judge_type=None,
                overlap=0.0, matched=False, type_correct=None,
            ))
    # Unmatched judge → false positives
    for j, jc in enumerate(judge_claims):
        if j not in matched_j:
            pairs.append(ClaimPair(
                gold_id=None, gold_span=None, gold_type=None,
                judge_span=jc["span"], judge_type=jc["type"],
                overlap=0.0, matched=False, type_correct=None,
            ))

    return StepAlignment(step_id=step_id, n_gold=len(gold_claims),
                         n_judge=len(judge_claims), pairs=pairs)


# ── Per-trajectory alignment ──────────────────────────────────────────────────

@dataclass
class TrajAlignment:
    traj_id: str
    steps: list[StepAlignment]

    @property
    def n_gold(self) -> int:
        return sum(s.n_gold for s in self.steps)

    @property
    def n_judge(self) -> int:
        return sum(s.n_judge for s in self.steps)

    @property
    def n_matched(self) -> int:
        return sum(s.n_matched for s in self.steps)

    @property
    def n_type_correct(self) -> int:
        return sum(s.n_type_correct for s in self.steps)

    # micro-averaged (pool all claims across steps)
    @property
    def span_recall(self) -> float:
        return self.n_matched / self.n_gold if self.n_gold else 1.0

    @property
    def span_precision(self) -> float:
        return self.n_matched / self.n_judge if self.n_judge else 1.0

    @property
    def type_accuracy(self) -> float:
        return self.n_type_correct / self.n_matched if self.n_matched else 0.0

    @property
    def f1(self) -> float:
        r, p = self.span_recall, self.span_precision
        return 2 * r * p / (r + p) if (r + p) else 0.0

    # type confusion matrix (gold_type -> judge_type -> count)
    def type_confusion(self) -> dict[str, Counter]:
        confusion: dict[str, Counter] = {}
        for step in self.steps:
            for pair in step.pairs:
                if not pair.matched:
                    continue
                gt = pair.gold_type or "?"
                jt = pair.judge_type or "?"
                if gt not in confusion:
                    confusion[gt] = Counter()
                confusion[gt][jt] += 1
        return confusion


def compute_traj_alignment(
    gold: GoldAnnotation,
    judge_path: Path,
    threshold: float = MATCH_THRESHOLD,
) -> TrajAlignment:
    judge_raw = json.loads(judge_path.read_text())
    judge_by_step = {s["step_id"]: s["claims"] for s in judge_raw}
    gold_by_step = {s.step_id: s.claims for s in gold.steps}

    all_step_ids = sorted(set(gold_by_step) | set(judge_by_step))
    step_aligns = []
    for sid in all_step_ids:
        step_aligns.append(align_step(
            step_id=sid,
            gold_claims=gold_by_step.get(sid, []),
            judge_claims=judge_by_step.get(sid, []),
            threshold=threshold,
        ))
    return TrajAlignment(traj_id=gold.traj_id, steps=step_aligns)


# ── CLI ───────────────────────────────────────────────────────────────────────

TRAJ_IDS = [
    "C-1_deepseek",
    "D-5_deepseek_r02",
    "H-2_deepseek",
    "PR-2_deepseek",
]

TRAJ_TO_JUDGE = {
    "C-1_deepseek":     (JUDGE_DIR, "C-1_gemini-pro_v1_judge.json"),
    # D-5_r02 gold is annotated against the _r02 trajectory; its judge output
    # lives in outputs/ (not results_deepseek_chat/independent/)
    "D-5_deepseek_r02": (BASE / "eval_v3-1_claim2action" / "stage1" / "outputs",
                         "D-5_deepseek_r02_gemini-pro_v1_judge.json"),
    "H-2_deepseek":     (JUDGE_DIR, "H-2_gemini-pro_v1_judge.json"),
    "PR-2_deepseek":    (JUDGE_DIR, "PR-2_gemini-pro_v1_judge.json"),
}


def _print_verbose(ta: TrajAlignment) -> None:
    """Print per-step detail and unmatched claims for a single trajectory."""
    print(f"\n{'─'*70}")
    print(f"  TRAJ: {ta.traj_id}")
    print(f"{'─'*70}")
    for sa in ta.steps:
        fn = [p for p in sa.pairs if not p.matched and p.gold_span]  # missed
        fp = [p for p in sa.pairs if not p.matched and p.judge_span]  # spurious
        tc = [p for p in sa.pairs if p.matched and not p.type_correct]  # type error
        print(f"\n  Step {sa.step_id:2d}  gold={sa.n_gold:3d} judge={sa.n_judge:3d} "
              f"matched={sa.n_matched:3d}  "
              f"R={sa.span_recall:.2f}  P={sa.span_precision:.2f}  "
              f"TypeAcc={sa.type_accuracy:.2f}")
        if fn:
            print(f"    MISSED ({len(fn)}):")
            for p in fn[:3]:
                print(f"      [{p.gold_type}] {p.gold_span[:65]!r}")
            if len(fn) > 3:
                print(f"      ... +{len(fn)-3} more")
        if fp:
            print(f"    SPURIOUS ({len(fp)}):")
            for p in fp[:3]:
                print(f"      [{p.judge_type}] {p.judge_span[:65]!r}")
            if len(fp) > 3:
                print(f"      ... +{len(fp)-3} more")
        if tc:
            print(f"    TYPE ERRORS ({len(tc)}):")
            for p in tc[:3]:
                print(f"      gold={p.gold_type} → judge={p.judge_type}  {p.gold_span[:55]!r}")
            if len(tc) > 3:
                print(f"      ... +{len(tc)-3} more")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--traj", default=None,
                        help="Run only this traj id (e.g. C-1_deepseek). Default: all 4.")
    parser.add_argument("--threshold", type=float, default=MATCH_THRESHOLD,
                        help=f"Token overlap threshold for a claim match (default {MATCH_THRESHOLD})")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show per-step breakdown + unmatched claims")
    parser.add_argument("--save-json", default=None,
                        help="Save full results to this JSON file")
    args = parser.parse_args()

    target_ids = [args.traj] if args.traj else TRAJ_IDS

    results: list[TrajAlignment] = []
    for tid in target_ids:
        gold_path = GOLD_DIR / f"{tid}.md"
        if tid not in TRAJ_TO_JUDGE:
            print(f"  [skip] {tid}: no judge mapping defined")
            continue
        if not gold_path.exists():
            print(f"  [skip] {tid}: gold annotation not found at {gold_path}")
            continue
        judge_dir, judge_fname = TRAJ_TO_JUDGE[tid]
        judge_path = judge_dir / judge_fname
        gold = parse_gold_annotation(gold_path)
        ta = compute_traj_alignment(gold, judge_path, threshold=args.threshold)
        results.append(ta)
        if args.verbose:
            _print_verbose(ta)

    if not results:
        print("No results.")
        return

    # ── Summary table ─────────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("  STAGE 1 HUMAN-JUDGE ALIGNMENT  (claim-level metrics)")
    print(f"  Match threshold: overlap ≥ {args.threshold:.0%}")
    print("=" * 72)
    hdr = f"  {'Trajectory':22s} {'N_gold':>7s} {'N_judge':>8s} {'Matched':>8s} {'Recall':>8s} {'Precision':>10s} {'TypeAcc':>8s}  {'F1':>6s}"
    print(hdr)
    print("  " + "─" * 68)
    for ta in results:
        print(f"  {ta.traj_id:22s} {ta.n_gold:>7d} {ta.n_judge:>8d} {ta.n_matched:>8d} "
              f"{ta.span_recall:>8.3f} {ta.span_precision:>10.3f} {ta.type_accuracy:>8.3f}  {ta.f1:>6.3f}")

    # Macro averages
    def macro(fn):
        vals = [fn(ta) for ta in results]
        return sum(vals) / len(vals)

    print("  " + "─" * 68)
    print(f"  {'Macro avg':22s} {'':>7s} {'':>8s} {'':>8s} "
          f"{macro(lambda t: t.span_recall):>8.3f} {macro(lambda t: t.span_precision):>10.3f} "
          f"{macro(lambda t: t.type_accuracy):>8.3f}  {macro(lambda t: t.f1):>6.3f}")

    # ── Per-type recall (all trajs pooled) ────────────────────────────────────
    type_gold: Counter = Counter()
    type_matched: Counter = Counter()
    for ta in results:
        for sa in ta.steps:
            for p in sa.pairs:
                if p.gold_type:
                    type_gold[p.gold_type] += 1
                    if p.matched:
                        type_matched[p.gold_type] += 1

    print()
    print("  Per-type recall (gold → how many judge found)")
    print(f"  {'Type':25s} {'N_gold':>8s} {'Matched':>8s} {'Recall':>8s}")
    print("  " + "─" * 55)
    for ctype in sorted(type_gold, key=lambda k: -type_gold[k]):
        n = type_gold[ctype]
        m = type_matched[ctype]
        print(f"  {ctype:25s} {n:>8d} {m:>8d} {m/n:>8.3f}")

    # ── Type confusion matrix (pooled) ────────────────────────────────────────
    confusion: dict[str, Counter] = {}
    for ta in results:
        for gt, cnt in ta.type_confusion().items():
            if gt not in confusion:
                confusion[gt] = Counter()
            confusion[gt].update(cnt)

    all_types = sorted({t for c in confusion.values() for t in c} | set(confusion.keys()))
    if all_types:
        print()
        print("  Type confusion matrix (rows = gold, cols = judge; only matched pairs)")
        col_w = max(len(t) for t in all_types) + 2
        header = f"  {'gold \\ judge':25s}" + "".join(f"{t:>{col_w}}" for t in all_types)
        print(header)
        print("  " + "─" * len(header))
        for gt in all_types:
            if gt not in confusion:
                continue
            row = f"  {gt:25s}" + "".join(f"{confusion[gt].get(jt, 0):>{col_w}}" for jt in all_types)
            print(row)

    # ── Save JSON ─────────────────────────────────────────────────────────────
    if args.save_json:
        out = []
        for ta in results:
            traj_out = {
                "traj_id": ta.traj_id,
                "n_gold": ta.n_gold, "n_judge": ta.n_judge,
                "n_matched": ta.n_matched, "n_type_correct": ta.n_type_correct,
                "span_recall": ta.span_recall, "span_precision": ta.span_precision,
                "type_accuracy": ta.type_accuracy, "f1": ta.f1,
                "steps": [
                    {
                        "step_id": sa.step_id,
                        "n_gold": sa.n_gold, "n_judge": sa.n_judge,
                        "n_matched": sa.n_matched,
                        "span_recall": sa.span_recall,
                        "span_precision": sa.span_precision,
                        "type_accuracy": sa.type_accuracy,
                        "pairs": [
                            {
                                "gold_id": p.gold_id, "gold_span": p.gold_span,
                                "gold_type": p.gold_type, "judge_span": p.judge_span,
                                "judge_type": p.judge_type, "overlap": round(p.overlap, 3),
                                "matched": p.matched, "type_correct": p.type_correct,
                            }
                            for p in sa.pairs
                        ],
                    }
                    for sa in ta.steps
                ],
            }
            out.append(traj_out)
        Path(args.save_json).write_text(json.dumps(out, indent=2, ensure_ascii=False))
        print(f"\nSaved → {args.save_json}")


if __name__ == "__main__":
    main()
