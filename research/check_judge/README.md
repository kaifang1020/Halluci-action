# check_judge

Compute agreement between human annotations (`research/annotations/*.md`) and
LLM-judge outputs (`research/eval_v2/stage{N}/outputs/md/*.md`).

## Quickstart

```bash
python -m research.check_judge.run --stage stage1
# → research/check_judge/results/stage1_agreement.json
```

Open [analysis.md](analysis.md) for the v1 stage-1 findings and recommended
follow-ups.

## What it computes

Per task and overall:

- **Atomic claim coverage** (set-level): Precision / Recall / F1 from aligning
  human claims with LLM claims (greedy max-score matching within each step;
  see `alignment.py` for the scorer).
- **Claim-type classification** (over aligned pairs): Accuracy, macro-F1,
  Cohen's κ, confusion matrix, per-class P/R/F1/support.
- **`requires_validation`** (over aligned pairs): same classification metrics.

Plus diagnostics in the per-task block:

- `matched_same_id` vs `matched_diff_id` — how often human and LLM use the
  same claim-id for the same content (low values = LLM uses a different
  numbering scheme).
- `unmatched_human_ids` / `unmatched_llm_ids` — the actual ids that became
  FN / FP, useful for spot-checking.

## CLI

```
python -m research.check_judge.run \
    --stage      stage1                                     \
    --llm-dir    research/eval_v2/stage1/outputs/md         \
    --human-dir  research/annotations                       \
    --output     research/check_judge/results/stage1_agreement.json \
    --threshold  0.5    # alignment score threshold
    --id-bonus   0.1    # bonus when claim_ids match
```

## Adding a new stage (e.g. stage 2)

When the stage-2 LLM judge starts emitting `gold_status` / `error_type` /
`severity`, **no parser/runner changes are needed**. Just:

1. Open `stages/stage2.py` and uncomment / adapt the `METRICS` template.
2. Run `python -m research.check_judge.run --stage stage2`.

The parser (`parsers.py`) already extracts those fields from both human and
LLM markdowns when present.

## Modules

| File | Purpose |
|---|---|
| `parsers.py` | Markdown → list of claim dicts. Handles both human and LLM schemas (optional fields). |
| `alignment.py` | Same-step greedy max-score matching with lexical hybrid scorer (token Jaccard + difflib.SequenceMatcher). Returns matched pairs + only_human + only_llm. |
| `classification.py` | Accuracy / macro-F1 / Cohen's κ / confusion / per-class metrics over aligned pairs. Uses `sklearn`. |
| `stages/stageN.py` | Declarative list of metrics to compute. `run.py` is stage-agnostic. |
| `run.py` | CLI entry point — discovers task overlap, runs metrics, writes JSON. |
| `tests/test_parsers.py` | Smoke test on D-5 (LLM 45 claims, human 48 claims). |

## Known limitations (v1)

- Lexical alignment misses semantic-but-not-lexical matches (e.g. "summarize"
  vs "introduce"). Upgrade path documented in `analysis.md` §6.2 — drop in
  SBERT or AlignScore by replacing `alignment.hybrid_score`.
- 4-task pilot (A-1, C-3, D-5, I-5). H-4 is excluded because the human file
  is empty. Numbers are illustrative until more annotations land.
- C-3 LLM output uses a different prompt/format from the other tasks (no
  `_judge_stage1` suffix); it's an outlier in the F1 numbers.


