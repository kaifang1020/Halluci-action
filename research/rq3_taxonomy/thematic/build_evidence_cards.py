#!/usr/bin/env python3
"""Step 1 of the RQ3 thematic classification: assemble one auditable evidence
card per halluci-action instance (736 total), joining the classified labels
with the raw evidence sources. All verbatim fields are exact copies — no LLM.

Sources:
  say-not-done (128, gates C1/C2/C3): stage2/proposed_requirement/outputs/not_supported_items.jsonl
  did-not-say  (608, gate C4):        eval_v3-2 .../outputs/<stem>_action_audit_enriched.jsonl (said=false)
  labels + judge reasons:             rq3_taxonomy/halluci_action_classified.jsonl

Output: evidence_cards.jsonl  (one card per instance, gate-tagged)
"""
from __future__ import annotations
import json
from collections import defaultdict, Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RQ3 = HERE.parent          # research/rq3_taxonomy
RESEARCH = RQ3.parent      # research/
EVAL4 = RESEARCH / "eval_v4"

CLASSIFIED = RQ3 / "halluci_action_classified.jsonl"
SAY_ITEMS = EVAL4 / "stage2/proposed_requirement/outputs/not_supported_items.jsonl"
DO_DIR = RESEARCH / "eval_v3-2_action2claim/stage3_action_annotation/outputs"
DO_STEMS = {"deepseek_chat": "real_deepseek", "deepseek_reasoner": "deepseek_reasoner",
            "gemini_flash": "gemini_flash", "gpt4o_mini": "openai_gpt_4o_mini", "qwen": "qwen"}

GATE = {"overclaimed-intent": "C1", "fabricated-completion": "C1", "wrong-target": "C2",
        "tool-failed-but-claimed": "C3", "unverified-assumption": "C3",
        "undisclosed-read": "C4", "silent-mutation": "C4", "covert-forbidden": "C4",
        "ambiguous": "X"}


def jl(p: Path):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def compact(v, n=160):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= n else s[: n - 1] + "…"


import re

def step_visible_text(sents, step):
    """Visible (non-reasoning) text of one step: assistant_sentences keeps
    <reasoning>...</reasoning> content as ordinary sentences, so strip those
    spans before deciding whether the step said anything user-visible."""
    joined = " ".join(s.get("text") or "" for s in sents if s.get("step_id") == step)
    return re.sub(r"<reasoning>.*?(</reasoning>|$)", " ", joined, flags=re.S).strip()


classified = jl(CLASSIFIED)
say_cls = [r for r in classified if r["direction"] == "say-not-done"]
do_cls = [r for r in classified if r["direction"] == "did-not-say"]

cards = []

# ---------- say-not-done: join classified rows to not_supported_items ----------
pool = defaultdict(list)
for it in jl(SAY_ITEMS):
    pool[(it["author_model"], it["task_id"])].append(it)

say_matched = 0
for r in say_cls:
    cands = pool.get((r["model"], r["task_id"]), [])
    hit = None
    for i, it in enumerate(cands):
        a, b = it["claim_span"].strip(), (r["headline"] or "").strip()
        if a[:80] == b[:80] or a.startswith(b) or b.startswith(a):
            hit = cands.pop(i)
            break
    if hit is None and cands:  # order-preserving fallback within (model, task)
        hit = cands.pop(0)
    assert hit is not None, f"no source item for {r['model']}/{r['task_id']}: {r['headline']!r}"
    say_matched += 1
    ctx = hit.get("assistant_context") or []
    calls = (hit.get("routed_action_evidence") or {}).get("tool_calls") or []
    cards.append({
        "card_id": hit["item_id"],
        "direction": "say-not-done",
        "gate": GATE[r["category"]],
        "category": r["category"],
        "model": r["model"], "domain": r["domain"], "task_id": r["task_id"],
        "condition": r["condition"], "complexity": r["complexity"],
        "severity": r["severity"], "requirement_status": r.get("requirement_status"),
        "claim_type": hit.get("claim_type"), "step_id": hit.get("step_id"),
        "verbatim": hit["claim_span"],
        "context": [{"sid": c["sentence_id"], "text": c["text"]} for c in ctx],
        "trace_evidence": [{"step": c.get("step_id"), "tool": c.get("tool_name"),
                            "params": compact(c.get("parameters"), 200)} for c in calls],
        "judge_reason": r.get("judge_reason"),
        "trajectory_path": hit.get("trajectory_path"),
    })

# ---------- did-not-say: derive from enriched files, verify against classified ----------
def do_category(x):
    if x.get("requirement_status") == "forbidden":
        return "covert-forbidden"
    if x.get("is_mutation"):
        return "silent-mutation"
    return "undisclosed-read"


do_count = Counter()
for model, stem in DO_STEMS.items():
    for x in jl(DO_DIR / f"{stem}_action_audit_enriched.jsonl"):
        if x["said"]:
            continue
        cat = do_category(x)
        do_count[cat] += 1
        tr = x.get("tool_result") or {}
        res = tr.get("result")
        sents = x.get("assistant_sentences") or []
        step = x.get("step_id")
        near = [s for s in sents if abs((s.get("step_id") or 0) - (step or 0)) <= 1][:6]
        cards.append({
            "card_id": f"{model}__{x['item_id']}",
            "direction": "did-not-say",
            "gate": GATE[cat],
            "category": cat,
            "model": model, "domain": x["domain"], "task_id": x["task_id"],
            "condition": x["condition"], "complexity": None,
            "severity": {"covert-forbidden": "forbidden", "silent-mutation": "write",
                         "undisclosed-read": "read"}[cat],
            "requirement_status": x.get("requirement_status"),
            "claim_type": None, "step_id": step,
            "verbatim": f"{x['tool_name']}({json.dumps(x.get('parameters'), ensure_ascii=False)})",
            "context": [{"sid": s["sentence_id"], "text": s["text"]} for s in near],
            "trace_evidence": [{"step": step, "tool": x["tool_name"],
                                "params": compact(x.get("parameters"), 200),
                                "result": compact(res, 200) if res is not None else None}],
            "judge_reason": x.get("said_reason"),
            "requirement_reason": x.get("requirement_reason"),
            "disclosure_timing": x.get("disclosure_timing"),
            "authorization": x.get("authorization"),
            "step_has_visible_text": bool(step_visible_text(sents, step)),
            "trajectory_path": x.get("trajectory_path"),
        })

# ---------- checks ----------
gate_count = Counter(c["gate"] for c in cards)
cat_count = Counter(c["category"] for c in cards)
expect_cat = Counter(r["category"] for r in classified)
print("say matched:", say_matched, "/", len(say_cls))
print("gate counts:", dict(gate_count))
print("category counts match classified:", cat_count == expect_cat)
if cat_count != expect_cat:
    print("  built   :", dict(cat_count))
    print("  expected:", dict(expect_cat))

out = HERE / "evidence_cards.jsonl"
out.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cards) + "\n")
print(f"wrote {len(cards)} cards -> {out}")
