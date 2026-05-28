from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from research.eval_v3.stage1.parse_gold import GoldAnnotation, GoldClaim, GoldStep
from research.eval_v3.stage1.judge import JudgeClaim, JudgeStep


def word_tokens(text: str) -> list[str]:
    return text.lower().split()


def word_intersection(a: str, b: str) -> int:
    ca = Counter(word_tokens(a))
    cb = Counter(word_tokens(b))
    return sum((ca & cb).values())


def greedy_match(
    gold_claims: list[GoldClaim],
    judge_claims: list[JudgeClaim],
) -> list[tuple[GoldClaim | None, JudgeClaim | None, int]]:
    """
    Greedy bipartite matching maximising total word intersection.
    Each gold and each judge span is used at most once.
    Returns triples (gold, judge, intersection):
      - matched pair: both non-None, intersection >= 0
      - unmatched gold (FN): (gold, None, 0)
      - unmatched judge (FP): (None, judge, 0)
    """
    if not gold_claims and not judge_claims:
        return []
    if not gold_claims:
        return [(None, j, 0) for j in judge_claims]
    if not judge_claims:
        return [(g, None, 0) for g in gold_claims]

    # Score matrix
    scores = [
        [word_intersection(g.span, j.span) for j in judge_claims]
        for g in gold_claims
    ]

    matched_gold: set[int] = set()
    matched_judge: set[int] = set()
    pairs: list[tuple[GoldClaim | None, JudgeClaim | None, int]] = []

    # Collect all (score, gi, ji), sort descending
    all_pairs = sorted(
        [
            (scores[gi][ji], gi, ji)
            for gi in range(len(gold_claims))
            for ji in range(len(judge_claims))
        ],
        reverse=True,
    )

    for score, gi, ji in all_pairs:
        if score == 0:
            break
        if gi in matched_gold or ji in matched_judge:
            continue
        pairs.append((gold_claims[gi], judge_claims[ji], score))
        matched_gold.add(gi)
        matched_judge.add(ji)

    for gi, g in enumerate(gold_claims):
        if gi not in matched_gold:
            pairs.append((g, None, 0))
    for ji, j in enumerate(judge_claims):
        if ji not in matched_judge:
            pairs.append((None, j, 0))

    return pairs


@dataclass
class ClaimResult:
    gold_span: str | None
    judge_span: str | None
    gold_type: str | None
    judge_type: str | None
    gold_words: int   # 0 for FP
    judge_words: int  # 0 for FN
    intersection: int

    @property
    def precision(self) -> float:
        return self.intersection / self.judge_words if self.judge_words > 0 else 0.0

    @property
    def recall(self) -> float:
        return self.intersection / self.gold_words if self.gold_words > 0 else 0.0

    @property
    def type_correct(self) -> bool | None:
        """None for FP/FN (no counterpart to compare). True/False for matched pairs."""
        if self.gold_span is None or self.judge_span is None:
            return None
        return self.gold_type == self.judge_type

    def to_dict(self) -> dict:
        return {
            "gold_span": self.gold_span,
            "judge_span": self.judge_span,
            "gold_type": self.gold_type,
            "judge_type": self.judge_type,
            "type_correct": self.type_correct,
            "gold_words": self.gold_words,
            "judge_words": self.judge_words,
            "intersection": self.intersection,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
        }


@dataclass
class StepResult:
    step_id: int
    claims: list[ClaimResult] = field(default_factory=list)

    @property
    def total_intersection(self) -> int:
        return sum(c.intersection for c in self.claims)

    @property
    def total_gold_words(self) -> int:
        return sum(c.gold_words for c in self.claims)

    @property
    def total_judge_words(self) -> int:
        return sum(c.judge_words for c in self.claims)

    @property
    def precision(self) -> float:
        d = self.total_judge_words
        return self.total_intersection / d if d > 0 else 0.0

    @property
    def recall(self) -> float:
        d = self.total_gold_words
        return self.total_intersection / d if d > 0 else 0.0

    @property
    def type_accuracy(self) -> float | None:
        matched = [c for c in self.claims if c.type_correct is not None]
        if not matched:
            return None
        return sum(1 for c in matched if c.type_correct) / len(matched)

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "type_accuracy": round(self.type_accuracy, 4) if self.type_accuracy is not None else None,
            "total_intersection": self.total_intersection,
            "total_gold_words": self.total_gold_words,
            "total_judge_words": self.total_judge_words,
            "claims": [c.to_dict() for c in self.claims],
        }


@dataclass
class TrajResult:
    traj_id: str
    steps: list[StepResult] = field(default_factory=list)

    @property
    def total_intersection(self) -> int:
        return sum(s.total_intersection for s in self.steps)

    @property
    def total_gold_words(self) -> int:
        return sum(s.total_gold_words for s in self.steps)

    @property
    def total_judge_words(self) -> int:
        return sum(s.total_judge_words for s in self.steps)

    @property
    def precision(self) -> float:
        d = self.total_judge_words
        return self.total_intersection / d if d > 0 else 0.0

    @property
    def recall(self) -> float:
        d = self.total_gold_words
        return self.total_intersection / d if d > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def type_accuracy(self) -> float | None:
        matched = [c for s in self.steps for c in s.claims if c.type_correct is not None]
        if not matched:
            return None
        return sum(1 for c in matched if c.type_correct) / len(matched)

    @property
    def cohen_kappa(self) -> float | None:
        matched = [c for s in self.steps for c in s.claims if c.type_correct is not None]
        if not matched:
            return None
        n = len(matched)
        gold_labels = [c.gold_type for c in matched]
        judge_labels = [c.judge_type for c in matched]
        p_o = sum(g == j for g, j in zip(gold_labels, judge_labels)) / n
        gold_counts = Counter(gold_labels)
        judge_counts = Counter(judge_labels)
        all_types = set(gold_counts) | set(judge_counts)
        p_e = sum((gold_counts[t] / n) * (judge_counts[t] / n) for t in all_types)
        return (p_o - p_e) / (1 - p_e) if (1 - p_e) > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "traj_id": self.traj_id,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "type_accuracy": round(self.type_accuracy, 4) if self.type_accuracy is not None else None,
            "cohen_kappa": round(self.cohen_kappa, 4) if self.cohen_kappa is not None else None,
            "total_intersection": self.total_intersection,
            "total_gold_words": self.total_gold_words,
            "total_judge_words": self.total_judge_words,
            "steps": [s.to_dict() for s in self.steps],
        }


def evaluate_step(gold_step: GoldStep, judge_step: JudgeStep | None) -> StepResult:
    gold_claims = gold_step.claims
    judge_claims = judge_step.claims if judge_step else []

    pairs = greedy_match(gold_claims, judge_claims)

    claim_results = []
    for gold, judge, intersection in pairs:
        gold_words = len(word_tokens(gold.span)) if gold else 0
        judge_words = len(word_tokens(judge.span)) if judge else 0
        claim_results.append(
            ClaimResult(
                gold_span=gold.span if gold else None,
                judge_span=judge.span if judge else None,
                gold_type=gold.type if gold else None,
                judge_type=judge.type if judge else None,
                gold_words=gold_words,
                judge_words=judge_words,
                intersection=intersection,
            )
        )

    return StepResult(step_id=gold_step.step_id, claims=claim_results)


def evaluate_traj(gold: GoldAnnotation, judge_steps: list[JudgeStep]) -> TrajResult:
    judge_by_step = {js.step_id: js for js in judge_steps}

    step_results = []
    for gold_step in gold.steps:
        judge_step = judge_by_step.get(gold_step.step_id)
        step_results.append(evaluate_step(gold_step, judge_step))

    return TrajResult(traj_id=gold.traj_id, steps=step_results)
