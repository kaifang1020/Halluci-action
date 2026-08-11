#!/usr/bin/env python3
"""Print compact evidence cards for one gate/category slice (A-track coding view).
Usage: print_batch.py <gate|category> [start] [end]
Model name is hidden from the coding view by design."""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sel, start, end = sys.argv[1], int(sys.argv[2] or 0) if len(sys.argv) > 2 else 0, \
    int(sys.argv[3]) if len(sys.argv) > 3 else 10 ** 9
cards = [json.loads(l) for l in (HERE / "evidence_cards.jsonl").read_text().splitlines()]
sub = [c for c in cards if c["gate"] == sel or c["category"] == sel]
for i, c in enumerate(sub):
    if not (start <= i < end):
        continue
    print(f"[{i}] {c['card_id']}  ({c['category']}, {c.get('claim_type') or '-'}, "
          f"req={c.get('requirement_status')}, step={c.get('step_id')})")
    print(f"  SAYS: {c['verbatim'][:220]}")
    ctx = c.get("context") or []
    for s in ctx[:5]:
        print(f"  ctx {s['sid']}: {s['text'][:130]}")
    for t in (c.get("trace_evidence") or [])[:4]:
        r = f" -> {t.get('result')[:90]}" if t.get("result") else ""
        print(f"  DID s{t.get('step')}: {t.get('tool')}({(t.get('params') or '')[:130]}){r}")
    print(f"  WHY: {(c.get('judge_reason') or '')[:260]}")
    print()
