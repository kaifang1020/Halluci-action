"""Judge-reliability agreement for the AppWorld pipeline (judge label vs human gold).

Mirrors the Odoo `research/check_judge` idea — accuracy, macro-F1, Cohen's kappa,
confusion matrix, per-class P/R/F1 — but:

  * dependency-free (no sklearn/numpy; the venv stubs numpy for run_har_metrics and
    we don't want to perturb that). Formulas are the textbook ones; a self-test
    (`--selftest`) checks them against a hand-computed example.
  * items are already ALIGNED by id (the human labels the SAME claim_id / action_id
    the judge scored — a blind random sample), so there is NO fuzzy claim matching
    like Odoo stage-1. We just inner-join on id.

Output schema matches check_judge/classification.pairwise_metrics so the AppWorld
numbers sit next to the Odoo ones.

Round-1 fields (see run_pipeline / run_action_centric):
    fidelity          : judge `verdict`            ∈ {supported, not_supported}
    said              : judge `said`               ∈ {true, false}
    requirement_status: judge `requirement_status` ∈ {required, allowed_supporting,
                                                       unnecessary, forbidden, unclear}

Usage:
    # fidelity: join stage-2 verdicts (llm) with a filled human worksheet (gold)
    python check_judge_appworld.py \
        --llm  runs/validation/stage2_*_verdicts.jsonl \
        --gold runs/validation/worksheet_fidelity.FILLED.jsonl \
        --field verdict --id-key claim_id --gold-key human_verdict \
        --out  runs/validation/agreement_fidelity.json

    python check_judge_appworld.py --selftest
"""
from __future__ import annotations

import argparse
import glob
import json
from collections import Counter
from pathlib import Path
from typing import Any


# ---------- metrics (dependency-free) ----------

def _confusion(h: list[str], l: list[str], labels: list[str]) -> dict[str, dict[str, int]]:
    idx = {lab: i for i, lab in enumerate(labels)}
    m = [[0] * len(labels) for _ in labels]
    for a, b in zip(h, l):
        m[idx[a]][idx[b]] += 1
    out: dict[str, dict[str, int]] = {}
    for i, hl in enumerate(labels):
        row = {labels[j]: m[i][j] for j in range(len(labels)) if m[i][j] > 0}
        if row:
            out[hl] = row
    return out


def _cohen_kappa(h: list[str], l: list[str], labels: list[str]) -> float:
    """Cohen's kappa = (po - pe) / (1 - pe)."""
    n = len(h)
    if n == 0:
        return 0.0
    po = sum(1 for a, b in zip(h, l) if a == b) / n
    hc = Counter(h)
    lc = Counter(l)
    pe = sum((hc.get(lab, 0) / n) * (lc.get(lab, 0) / n) for lab in labels)
    if abs(1 - pe) < 1e-12:
        return 1.0  # perfect-by-chance (all one label, and they agree) -> define as 1.0
    return (po - pe) / (1 - pe)


def _per_class(h: list[str], l: list[str], labels: list[str]) -> dict[str, dict]:
    """One-vs-rest P/R/F1 per label. Human = truth, LLM = prediction (matches
    check_judge: precision_recall_fscore_support(y_true=human, y_pred=llm))."""
    hc = Counter(h)
    lc = Counter(l)
    out: dict[str, dict] = {}
    for lab in labels:
        if hc.get(lab, 0) == 0 and lc.get(lab, 0) == 0:
            continue
        tp = sum(1 for a, b in zip(h, l) if a == lab and b == lab)
        pred_pos = lc.get(lab, 0)          # llm predicted this label
        true_pos = hc.get(lab, 0)          # human truth is this label
        precision = tp / pred_pos if pred_pos else 0.0
        recall = tp / true_pos if true_pos else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        out[lab] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support_human": int(true_pos),
            "support_llm": int(pred_pos),
        }
    return out


def pairwise_metrics(pairs: list[dict], field: str, labels: list[str] | None = None) -> dict:
    """pairs: [{"human": {field: ...}, "llm": {field: ...}}]. Skips pairs where
    either side is null. Output schema == check_judge/classification.pairwise_metrics."""
    h_vals, l_vals = [], []
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
        return {"n_pairs": n_pairs, "n_evaluated": 0, "accuracy": None, "macro_f1": None,
                "cohen_kappa": None, "labels": list(labels) if labels else [], "confusion": {},
                "per_class": {}}

    label_list = sorted(set(labels or []) | set(h_vals) | set(l_vals))
    accuracy = sum(1 for a, b in zip(h_vals, l_vals) if a == b) / n_eval
    kappa = _cohen_kappa(h_vals, l_vals, label_list)
    per_class = _per_class(h_vals, l_vals, label_list)
    macro_f1 = sum(c["f1"] for c in per_class.values()) / len(per_class) if per_class else 0.0
    return {
        "n_pairs": n_pairs,
        "n_evaluated": n_eval,
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "cohen_kappa": round(float(kappa), 4),
        "labels": label_list,
        "confusion": _confusion(h_vals, l_vals, label_list),
        "per_class": per_class,
    }


# ---------- IO ----------

def _load_jsonl(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _norm(v: Any) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def build_pairs(llm_rows: list[dict], gold_rows: list[dict], *, id_key: str,
                llm_field: str, gold_field: str) -> tuple[list[dict], dict]:
    """Inner-join judge rows and human rows on id_key. Returns (pairs, diagnostics)."""
    llm_by = {r[id_key]: r for r in llm_rows if id_key in r}
    pairs, matched, missing_llm = [], [], []
    used = set()
    for g in gold_rows:
        gid = g.get(id_key)
        gv = _norm(g.get(gold_field))
        if gv is None:
            continue  # unlabeled worksheet row — skip
        lr = llm_by.get(gid)
        if lr is None:
            missing_llm.append(gid)
            continue
        used.add(gid)
        pairs.append({"id": gid,
                      "human": {"label": gv},
                      "llm": {"label": _norm(lr.get(llm_field))}})
        matched.append(gid)
    diag = {"n_gold_labeled": sum(1 for g in gold_rows if _norm(g.get(gold_field)) is not None),
            "n_matched": len(matched),
            "n_gold_without_llm": len(missing_llm),
            "missing_llm_ids": missing_llm[:20]}
    return pairs, diag


# ---------- self-test ----------

def _selftest() -> None:
    # hand-computed 2x2: human=[s,s,s,ns,ns], llm=[s,s,ns,ns,ns]
    #   agree on 4/5 -> acc .8 ; confusion s->{s:2,ns:1}, ns->{ns:2}
    #   po=.8 ; pe = P(s)_h*P(s)_l + P(ns)_h*P(ns)_l = (3/5)(2/5)+(2/5)(3/5)=.24+.24=.48
    #   kappa=(.8-.48)/(1-.48)=.32/.52=.6154
    pairs = [{"human": {"v": h}, "llm": {"v": l}} for h, l in
             zip(["s", "s", "s", "ns", "ns"], ["s", "s", "ns", "ns", "ns"])]
    m = pairwise_metrics(pairs, "v", labels=["s", "ns"])
    assert m["accuracy"] == 0.8, m["accuracy"]
    assert m["cohen_kappa"] == 0.6154, m["cohen_kappa"]
    # class s: tp=2, pred_pos(llm=s)=2 -> P=1.0 ; true_pos(human=s)=3 -> R=.6667
    assert m["per_class"]["s"]["precision"] == 1.0, m["per_class"]["s"]
    assert m["per_class"]["s"]["recall"] == 0.6667, m["per_class"]["s"]
    assert m["confusion"]["s"] == {"s": 2, "ns": 1}, m["confusion"]
    print("selftest OK:", {k: m[k] for k in ("accuracy", "macro_f1", "cohen_kappa")})


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--llm", nargs="*", default=[], help="judge output jsonl(s) (globs ok)")
    p.add_argument("--gold", nargs="*", default=[], help="filled human worksheet jsonl(s) (globs ok)")
    p.add_argument("--field", default="verdict", help="judge field name (e.g. verdict / said / requirement_status)")
    p.add_argument("--id-key", default="claim_id", help="join key (claim_id / action_id)")
    p.add_argument("--gold-key", default=None, help="human label field (default: human_<field>)")
    p.add_argument("--labels", nargs="*", default=None, help="label universe (optional)")
    p.add_argument("--group-by", default=None, help="judge-row key to break metrics down by (e.g. judge_model)")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    if args.selftest:
        _selftest()
        return

    llm_paths = [Path(x) for g in args.llm for x in glob.glob(g)]
    gold_paths = [Path(x) for g in args.gold for x in glob.glob(g)]
    if not llm_paths or not gold_paths:
        p.error("need --llm and --gold (or --selftest)")
    gold_key = args.gold_key or f"human_{args.field}"

    llm_rows = _load_jsonl(llm_paths)
    gold_rows = _load_jsonl(gold_paths)

    def _report(llm_subset: list[dict]) -> dict:
        pairs, diag = build_pairs(llm_subset, gold_rows, id_key=args.id_key,
                                  llm_field=args.field, gold_field=gold_key)
        # pairwise_metrics reads field "label" (build_pairs normalized both sides to it)
        m = pairwise_metrics(pairs, "label", labels=args.labels)
        m["diagnostics"] = diag
        return m

    result: dict[str, Any] = {"field": args.field, "id_key": args.id_key, "gold_key": gold_key,
                              "n_llm_rows": len(llm_rows), "n_gold_rows": len(gold_rows)}
    if args.group_by:
        groups = sorted({str(r.get(args.group_by)) for r in llm_rows})
        result["by_" + args.group_by] = {
            g: _report([r for r in llm_rows if str(r.get(args.group_by)) == g]) for g in groups}
    result["overall"] = _report(llm_rows)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
