#!/usr/bin/env python3
"""Step 2 (B-track): stratify the 586 undisclosed-read instances by the
relation between the action and the visible narration, using the audit
judge's said_reason plus the step's visible-text flag.

Strata (final, after manual review of every step-has-text instance):
  silent-step        — the step containing the call produced no visible assistant text
  reasoning-only     — the action is mentioned only inside hidden reasoning/thinking
  narration-mismatch — the step has visible narration, but it does not cover this
                       action (describes a different action, a vaguer plan, or only
                       the step's other calls)

Also emits per-stratum × model counts and dumps narration-mismatch for audit.
"""
import json, re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
cards = [json.loads(l) for l in (HERE / "evidence_cards.jsonl").read_text().splitlines()]
reads = [c for c in cards if c["category"] == "undisclosed-read"]

RE_REASONING = re.compile(
    r"hidden reasoning|reasoning block|thinking block|only .{0,40}(inside|in) (the )?(hidden|internal) reasoning"
    r"|internal reasoning|reasoning ta(g|gs)|<think", re.I)


def stratum(c):
    r = c.get("judge_reason") or ""
    if RE_REASONING.search(r):
        return "reasoning-only"
    if not c.get("step_has_visible_text"):
        return "silent-step"
    return "narration-mismatch"


for c in reads:
    c["c4_stratum"] = stratum(c)

cnt = Counter(c["c4_stratum"] for c in reads)
print("strata:", dict(cnt), f" residual rate = {cnt['residual']/len(reads):.1%}")

by_model = Counter((c["c4_stratum"], c["model"]) for c in reads)
models = sorted({c["model"] for c in reads})
with open(HERE / "c4_read_strata.tsv", "w") as f:
    f.write("stratum\ttotal\t" + "\t".join(models) + "\n")
    for s in ["silent-step", "reasoning-only", "narration-mismatch"]:
        f.write(s + f"\t{cnt[s]}\t" + "\t".join(str(by_model[(s, m)]) for m in models) + "\n")

# position of the action relative to the trajectory's final step (pre/post answer proxy)
with open(HERE / "c4_read_assignments.jsonl", "w") as f:
    for c in reads:
        f.write(json.dumps({"card_id": c["card_id"], "stratum": c["c4_stratum"],
                            "model": c["model"], "task_id": c["task_id"]},
                           ensure_ascii=False) + "\n")

res = [c for c in reads if c["c4_stratum"] == "narration-mismatch"]
with open(HERE / "c4_read_narration_mismatch.txt", "w") as f:
    for c in res:
        f.write(f"--- {c['card_id']}\n  action: {c['verbatim'][:140]}\n"
                f"  reason: {(c.get('judge_reason') or '')[:300]}\n"
                f"  visible_text_in_step: {c.get('step_has_visible_text')}\n")
print(f"wrote c4_read_strata.tsv, c4_read_assignments.jsonl, {len(res)} residuals")
