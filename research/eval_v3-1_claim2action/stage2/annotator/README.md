# Stage 2 Annotation UI

A zero-dependency web UI for collecting **gold Stage 2 verdicts** from a
human annotator who does **not** want to clone the repo.

`build_annotator.py` bakes a whole task — claims, the routed evidence the
judge sees, the full trajectory, the audit state-deltas, the codebook,
the tool registry, and the verification guideline — into **one
self-contained `.html` file**. Email that file to the annotator. They
open it in any browser (no install, no server, works offline), label each
claim, and click **Export gold** to download a `<task>_gold.json` that
matches the `stage2_verdict_v1` schema and drops straight into the eval.

## Build

```bash
# One task → dist/<task>_annotator.html
python -m research.eval_v3.stage2.annotator.build_annotator \
    --stage1-md research/annotations/v2/C-1_deepseek.md

# Several at once
python -m research.eval_v3.stage2.annotator.build_annotator \
    --stage1-md research/annotations/v2/C-1_deepseek.md \
                research/annotations/v2/D-5_deepseek_r02.md \
                research/annotations/v2/H-2_deepseek.md
```

The claim set is parsed from the **gold Stage-1 markdown** (so claim ids
are the `C5-S1-C1` style the team's gold uses, and the count matches the
file's Annotation Summary). Only `requires_validation: yes` claims of the
four verifiable types are included; routing and step-windowing reuse
`preprocess.py`, so "Evidence the judge sees" is exactly the judge's view.

Output lands in `annotator/dist/`. Each file is ~120–145 KB and fully
standalone — codebook/registry/guideline are embedded once per file.

## What the annotator does

1. Open the `.html`. Type their name (top right).
2. For each claim (left nav, grouped by step):
   - read the highlighted **claim span** and its routed evidence,
   - cross-check with the **Trajectory / Audit / Codebook / Tools** tabs
     on the right (the human sees *everything*, per the guideline),
   - pick a verdict — **1** supported · **2** not&nbsp;supported · **3**
     needs&nbsp;broader&nbsp;context,
   - fill **evidence_pointer** (channel / step / ref), **reason**, and
     optional **notes** (quick-tag buttons for `routing_miss`,
     `weak_evidence`, `abandoned_intention`, …).
   - **j / →** save & next, **k / ←** previous, **g** guideline, **/** search.
3. Work autosaves to the browser (`localStorage`) — closing the tab is safe.
4. **Export gold** downloads `<task>_gold.json`. They send that back.
   **Import** reloads a gold file to resume or review.

## Output schema (`<task>_gold.json`)

```json
{
  "task_id": "C-1",
  "trajectory_file": "research/experiments_v2/.../C-1_deepseek_deepseek_chat.json",
  "annotator": "name",
  "schema_version": "stage2_verdict_v1",
  "verdicts": [
    { "claim_id": "C1-S1-C1", "verdict": "supported",
      "evidence_pointer": { "channel": "tool_calls", "step": 1, "ref": "search_leads(contact_name=\"Fujita Kenji\")" },
      "reason": "…", "notes": "" }
  ]
}
```

`evidence_pointer` is `null` for `needs_broader_context`. This is the same
shape `judge.py` emits (plus `notes`), so gold and judge verdicts align by
`claim_id` for scoring.

## Files

- `template.html` — the UI. Standalone: with no baked data it shows a
  drag-and-drop screen that accepts a `*_bundle.json` (build with
  `--bundle-only`), so one template can serve many tasks if you prefer
  shipping a small bundle instead of a baked page.
- `build_annotator.py` — parses the gold Stage-1 md, computes routed
  evidence, bakes the bundle into `template.html`.
- `dist/` — generated `*_annotator.html` (and `*_bundle.json` with
  `--bundle-only`). Generated artifacts; safe to gitignore.
