"""Classification metrics over aligned (human, llm) claim pairs.

Computes accuracy, macro-F1, Cohen's kappa, confusion matrix, and per-class
P/R/F1/support for any categorical field (e.g. ``type``, ``requires_validation``,
or future ``gold_status``).
"""

from __future__ import annotations

from typing import Iterable

from sklearn.metrics import (
    cohen_kappa_score,
    confusion_matrix,
    precision_recall_fscore_support,
)


def pairwise_metrics(
    pairs: Iterable[dict],
    field: str,
    labels: Iterable[str] | None = None,
) -> dict:
    """Compute classification agreement between human and LLM on a categorical field.

    Parameters
    ----------
    pairs : iterable of {"human": dict, "llm": dict, ...}
        Aligned claim pairs (output of ``alignment.align``).
    field : str
        Field to compare (e.g. ``"type"``).
    labels : iterable[str] | None
        Label universe. If provided, also reports labels with zero support.

    Returns
    -------
    {
        "n_pairs": int,
        "n_evaluated": int,        # pairs where both sides had non-null value
        "accuracy": float,
        "macro_f1": float,
        "cohen_kappa": float,
        "labels": [...],
        "confusion": {h_label: {l_label: count}},
        "per_class": {label: {precision, recall, f1, support_human, support_llm}},
    }
    """
    pairs = list(pairs)
    h_vals: list[str] = []
    l_vals: list[str] = []
    for p in pairs:
        h = p.get("human", {}).get(field)
        l = p.get("llm", {}).get(field)
        if h is None or l is None:
            continue
        h_vals.append(str(h))
        l_vals.append(str(l))

    n_pairs = len(pairs)
    n_eval = len(h_vals)
    if n_eval == 0:
        return {
            "n_pairs": n_pairs,
            "n_evaluated": 0,
            "accuracy": None,
            "macro_f1": None,
            "cohen_kappa": None,
            "labels": list(labels) if labels else [],
            "confusion": {},
            "per_class": {},
        }

    label_list = sorted(set(labels) | set(h_vals) | set(l_vals)) if labels else sorted(set(h_vals) | set(l_vals))

    accuracy = sum(1 for a, b in zip(h_vals, l_vals) if a == b) / n_eval
    kappa = cohen_kappa_score(h_vals, l_vals, labels=label_list)
    precisions, recalls, f1s, supports = precision_recall_fscore_support(
        h_vals,
        l_vals,
        labels=label_list,
        zero_division=0,
    )
    macro_f1 = float(sum(f1s) / len(f1s)) if len(f1s) else 0.0

    cm = confusion_matrix(h_vals, l_vals, labels=label_list)
    confusion: dict[str, dict[str, int]] = {}
    for i, h_label in enumerate(label_list):
        row = {l_label: int(cm[i][j]) for j, l_label in enumerate(label_list) if cm[i][j] > 0}
        if row:
            confusion[h_label] = row

    per_class: dict[str, dict] = {}
    h_counts = {lbl: h_vals.count(lbl) for lbl in label_list}
    l_counts = {lbl: l_vals.count(lbl) for lbl in label_list}
    for lbl, p, r, f, s in zip(label_list, precisions, recalls, f1s, supports):
        if h_counts[lbl] == 0 and l_counts[lbl] == 0:
            continue
        per_class[lbl] = {
            "precision": round(float(p), 4),
            "recall": round(float(r), 4),
            "f1": round(float(f), 4),
            "support_human": int(h_counts[lbl]),
            "support_llm": int(l_counts[lbl]),
        }

    return {
        "n_pairs": n_pairs,
        "n_evaluated": n_eval,
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "cohen_kappa": round(float(kappa), 4),
        "labels": label_list,
        "confusion": confusion,
        "per_class": per_class,
    }
