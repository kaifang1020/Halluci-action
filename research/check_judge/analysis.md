# Stage-1 Judge Agreement — Findings & Recommendations

Results file: [results/stage1_agreement.json](results/stage1_agreement.json)  
Run command: `python -m research.check_judge.run --stage stage1`

## 1. Headline numbers

| Metric (overall, micro-aggregated across 4 tasks) | Value |
|---|---|
| Atomic-claim extraction Precision / Recall / F1 | **0.754 / 0.846 / 0.797** |
| Claim-type Accuracy (on 104 aligned pairs) | **0.942** |
| Claim-type macro-F1 | 0.658 |
| Claim-type Cohen's κ | **0.913** (almost-perfect agreement) |
| `requires_validation` Accuracy | 1.000 (κ = N/A, see §4) |

**One-sentence read**: when the LLM extracts an atomic claim, it almost always tags the type correctly (κ ≈ 0.91), but it over-extracts about 20% more claims than human (34 FP vs 19 FN), so the extraction-F1 sits at 0.80.

## 2. Per-task breakdown

| Task | n_human | n_llm | TP | FP | FN | P | R | F1 | type κ | matched same_id / diff_id |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A-1 | 18 | 19 | 17 | 2 | 1 | 0.895 | 0.944 | 0.919 | 1.000 | 12 / 5 |
| C-3 | 25 | 37 | 17 | 20 | 8 | 0.460 | 0.680 | **0.548** | 1.000 | 10 / 7 |
| D-5 | 48 | 45 | 39 | 6 | 9 | 0.867 | 0.812 | 0.839 | 0.854 | 23 / 16 |
| I-5 | 32 | 37 | 31 | 6 | 1 | 0.838 | 0.969 | 0.899 | 0.901 | 5 / 26 |

### What jumps out

- **C-3 is a clear outlier** (F1 = 0.548 vs ≥0.84 elsewhere). The LLM extracted 37 claims for 25 human claims, with 20 FP and 8 FN. C-3 is also the only file in the LLM output dir without the `_judge_stage1` suffix — likely a different prompt version. Worth investigating before drawing conclusions about the judge overall.
- **I-5 shows almost no claim-id agreement** (5 same-id matches vs 26 different-id matches). Excellent F1 (0.90) despite this, which says the **id schema is unstable but the content is consistent** — argues against using claim_id as a primary match key (this is the issue we caught during planning).
- **A-1 has near-perfect agreement** — the simplest task (clean retrieval + report) with no actions/escalations; LLM and human aligned on practically everything.

## 3. Where the LLM judge actually fails

### 3.1 Over-extraction of "framing" / "header" text

Looking at FP lists:
- `A1-S2-C1` ("summarize overdue customer invoices") — human treats this as a single `non_actionable_text` framing claim too, but LLM also splits "Summary by Customer" as its own claim `A1-S2-C13`.
- `C-3` has 20 FP almost entirely in S2 — the LLM extracted line-by-line restatements of the same fact instead of one consolidated claim.

**Pattern**: LLM over-extracts when source has tables, bullet lists, or section headers. Each row/bullet/header becomes a separate claim, even when the human marks them all as part of one observation block.

### 3.2 Systematic `reasoning_conclusion` → `observation` drift

Confusion matrix (overall):

```
human            -> llm                    count
reasoning_conclusion -> observation         5      <- the only systematic mismatch
reasoning_conclusion -> reasoning_conclusion 16
observation        -> action_completion     1
observation        -> observation          48
action_intention   -> action_intention     26
constraint_or_policy -> constraint_or_policy 6
action_completion  -> action_completion     2
```

The LLM tags **24%** (5/21) of what humans call `reasoning_conclusion` as plain `observation`. Looking at examples from D-5 like "ticket ID 4 is the relevant Watanabe Mei ticket" — humans consider this a *conclusion drawn from* `partner_id=false` + name match, but the LLM reads it as a flat factual observation. This is precisely the kind of error a calibrated judge needs to catch: **observation vs conclusion changes whether a claim is grounded by tool output or by agent reasoning**.

### 3.3 Action-completion vs observation confusion (minor, 1 case)

LLM occasionally labels a "ticket ID 4 has been reassigned" claim as `action_completion` while human keeps it as `observation`. Borderline; doesn't seem systematic.

### 3.4 Missed claims (FN)

D-5 has 9 FN. Eyeballing: most are claims that the human added on top of LLM output (`D5-S8-C5` = "log interaction on Watanabe Mei customer record" is a human-only fine-grained split). These aren't really LLM errors — they're human-added granularity. Hard to call them "missed" without a granularity policy.

## 4. Metric caveats

- **`requires_validation` κ is NaN**: because matched LLM pairs are virtually all "yes". With one degenerate class, Cohen's κ is undefined. The 100% accuracy is real, but uninformative on disagreement.
- **macro-F1 is much lower than accuracy** (0.66 vs 0.94). This is class imbalance: `action_intention`, `observation`, `reasoning_conclusion` dominate; the rare types (`recommendation`, `non_actionable_text`) have small support and pull the macro mean down even when correct.
- **N = 4 tasks**. With only A-1, C-3, D-5, I-5 having both human and LLM annotations (H-4 human is empty), one outlier (C-3) shifts overall metrics significantly. **Add more annotations before drawing definitive conclusions.**
- **Alignment is lexical, not semantic**. Token Jaccard + difflib at threshold 0.5 is a deliberately shallow baseline (see §6 for the upgrade path). Some unmatched pairs are probably true semantic matches missed by surface dissimilarity.

## 5. What this means for the judge

Three concrete weaknesses identified:

1. **Granularity / boundary control**: the judge needs explicit guidance on when to consolidate vs split (tables, bullets, repeated facts).
2. **observation vs reasoning_conclusion**: judge prompt should explicitly require classifying as `reasoning_conclusion` whenever the claim **involves any inference step** beyond direct tool-output read.
3. **Type-system fidelity**: where the judge gets a claim, it gets the type right (κ = 0.91). So the prompt's type definitions are working — the gap is at the *extraction* stage, not the labeling stage.

## 6. Concrete next steps (ordered by cost/impact)

### 6.1 Short, free, do now

1. **Inspect why C-3 is bad** — different filename (no `_judge_stage1` suffix) hints at a different prompt or stage version. Fix or re-generate so all stage-1 outputs follow one schema.
2. **Add more annotations** to get above N=4. The current pilot set is too small for the type-confusion picture to stabilize.
3. **Tighten the extraction prompt** with 2-3 examples that disambiguate `observation` vs `reasoning_conclusion`. Best example: "ticket ID 4 *is the relevant* Watanabe Mei ticket" should be `reasoning_conclusion`; "ticket ID 4 has name 'Late delivery complaint'" should be `observation`.

### 6.2 Medium effort — upgrade the alignment metric

Replace the lexical hybrid with an **embedding-based matcher** to get a more defensible numerator/denominator. See `claim-alignment-eval/` for the literature review. Two concrete options:

| Backend | Model | Threshold | Strength |
|---|---|---|---|
| SBERT cosine | `sentence-transformers/all-MiniLM-L6-v2` (22 MB) | 0.65–0.75 | Cheap, fast, good for short claims |
| AlignScore | [`yzha/AlignScore`](https://huggingface.co/yzha/AlignScore) (355 M, ~1.5 GB) | 0.5 | Trained on 4.7M alignment examples; matches GPT-4 on factuality benchmarks at <1% of the cost |

Both are **frozen, deterministic models** — not "LLM-as-judge". The plan in `alignment.py` is already structured to allow swapping the `hybrid_score` function — should be ~30 lines of glue.

References from the lit review:
- AlignScore (Zha et al., ACL 2023) — the unified alignment metric most directly applicable here ([arXiv](https://arxiv.org/abs/2305.16739)).
- VeriFact (Liu et al., EMNLP 2025) — closest *task setup* to ours (reference vs candidate fact sets, bidirectional NLI matching with threshold; explicitly reports precision **and** recall) ([arXiv](https://arxiv.org/abs/2505.09701)).
- VeriScore (Song et al., EMNLP Findings 2024) — argues claim extraction should filter to verifiable, self-contained claims, with referents resolved ([arXiv](https://arxiv.org/abs/2406.19276)). Directly relevant to §3.1 (the over-extraction issue).
- Core (Jiang et al., 2024) — combinatorial deduplication of repeated/trivial sub-claims. Useful preprocessing if the judge keeps splitting tables row-by-row.
- RefChecker (Hu et al., EMNLP 2024) — triplet-based structured matching ([arXiv](https://arxiv.org/abs/2405.14486)). For the accounting/CRM domain this is an interesting alternative: extract `(entity, predicate, value)` triplets (invoice ID, customer, amount, status) and require slot-level equality. Likely the strongest deterministic option for `observation`-type claims with named entities.

### 6.3 Larger effort — if prompt-tuning still leaves gaps

- **Fine-tune the judge (SFT)**. Once we have ~30+ annotated trajectories, distill into a small judge (LLaMA-3 8B / Qwen-2 7B) following the VeriFastScore (Rajendhran et al., EMNLP 2025) recipe — they fine-tune Llama 3.1 8B on synthetic factuality data and reach 0.94 system-level correlation with the original LLM pipeline at 6.6× speedup ([arXiv](https://arxiv.org/abs/2505.16973)).
- Alternative: **Prometheus 2** / **JudgeLM** / **PandaLM** style judge fine-tuning — trains a dedicated judge from a base model with structured output and rationale.

### 6.4 What to NOT do

- **Don't add LLM-as-judge in the matching/eval pipeline.** That would make the eval itself circular and non-deterministic. Use frozen encoders only.
- **Don't optimize before having more annotations.** The C-3 outlier alone moves the F1 by ~5 absolute points; with 4 tasks we don't know which numbers are signal.

## 7. Reusability for stage-2

The directory is set up so that when the LLM judge eventually emits `gold_status` / `error_type` / `severity` (currently human-only), adding metrics for them takes ~10 lines: fill in `stages/stage2.py::METRICS` (template already in place), then run `python -m research.check_judge.run --stage stage2`. No change needed to `run.py`, `parsers.py`, `alignment.py`, or `classification.py`.
