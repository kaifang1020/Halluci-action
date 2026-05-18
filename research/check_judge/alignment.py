"""Align human claims with LLM claims; compute set-level P/R/F1.

v1 uses a lexical hybrid scorer (token Jaccard + difflib SequenceMatcher.ratio)
with a small bonus when claim_ids match exactly. Matching is greedy within
each step bucket. This is a deliberately simple, dependency-free baseline.

Known limitation: this is a lexical similarity, not a semantic one. Two
semantically-equivalent claims with different surface wording (e.g.
"introduce overdue invoice summary" vs "summarize overdue customer invoices")
can fall under the threshold. The analysis output records the alignment
parameters so this can be revisited (probably by swapping in SBERT or
AlignScore — see analysis.md).
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from typing import Iterable


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {tok.lower() for tok in _TOKEN_RE.findall(text or "")}


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def hybrid_score(text_a: str | None, text_b: str | None) -> float:
    """0.5 * token Jaccard + 0.5 * difflib SequenceMatcher ratio."""
    a = (text_a or "").strip()
    b = (text_b or "").strip()
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return 0.5 * _jaccard(a, b) + 0.5 * difflib.SequenceMatcher(None, a, b).ratio()


def align(
    human: list[dict],
    llm: list[dict],
    threshold: float = 0.5,
    id_bonus: float = 0.1,
) -> dict:
    """Same-step greedy max-score alignment.

    Scoring: ``hybrid_score(h.text, l.text) + id_bonus * (h.claim_id == l.claim_id)``.
    Claims are bucketed by ``step_id``; pairs are only considered within the
    same step. We greedily take the highest-scoring remaining pair until all
    remaining pairs score below the threshold.

    Returns
    -------
    {
        "params": {"threshold": ..., "id_bonus": ...},
        "matched": [{"human": h_claim, "llm": l_claim, "score": float, "same_id": bool}, ...],
        "only_human": [h_claim, ...],
        "only_llm":   [l_claim, ...],
    }
    """
    by_step_h: dict[int | None, list[dict]] = defaultdict(list)
    by_step_l: dict[int | None, list[dict]] = defaultdict(list)
    for h in human:
        by_step_h[h.get("step_id")].append(h)
    for l in llm:
        by_step_l[l.get("step_id")].append(l)

    matched: list[dict] = []
    only_human: list[dict] = []
    only_llm: list[dict] = []

    all_steps = set(by_step_h) | set(by_step_l)
    for step in sorted(all_steps, key=lambda x: (x is None, x)):
        h_pool = list(by_step_h.get(step, []))
        l_pool = list(by_step_l.get(step, []))

        # Build all candidate scores.
        candidates: list[tuple[float, int, int]] = []
        for i, h in enumerate(h_pool):
            for j, l in enumerate(l_pool):
                score = hybrid_score(h.get("text"), l.get("text"))
                if h.get("claim_id") == l.get("claim_id"):
                    score += id_bonus
                candidates.append((score, i, j))
        candidates.sort(reverse=True)

        used_h: set[int] = set()
        used_l: set[int] = set()
        for score, i, j in candidates:
            if score < threshold:
                break
            if i in used_h or j in used_l:
                continue
            used_h.add(i)
            used_l.add(j)
            h, l = h_pool[i], l_pool[j]
            matched.append(
                {
                    "human": h,
                    "llm": l,
                    "score": round(score, 4),
                    "same_id": h.get("claim_id") == l.get("claim_id"),
                }
            )

        only_human.extend(h for i, h in enumerate(h_pool) if i not in used_h)
        only_llm.extend(l for j, l in enumerate(l_pool) if j not in used_l)

    return {
        "params": {"threshold": threshold, "id_bonus": id_bonus},
        "matched": matched,
        "only_human": only_human,
        "only_llm": only_llm,
    }


def set_metrics(matched: Iterable[dict], only_human: Iterable[dict], only_llm: Iterable[dict]) -> dict:
    """Compute P/R/F1 from alignment outcome."""
    tp = len(list(matched))
    fp = len(list(only_llm))
    fn = len(list(only_human))
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }
