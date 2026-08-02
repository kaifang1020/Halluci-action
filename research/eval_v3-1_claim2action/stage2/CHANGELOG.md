# Stage 2 Judge — Prompt Version Changelog

Judge-error-driven fixes to the Stage 2 verification judge, archived for
the paper appendix / rebuttal. **v2** bundles three fixes found by
auditing the v1 verdicts (one per error category).

- **Prompt snapshots:** `prompt_versions/<ver>/{action_validation_guideline.md, propmt_template.md, stage2_examples.md}` — each independently re-runnable.
- **Evidence routing:** version-gated in `preprocess.py` (`routing_version`); selected by `run_stage2.py --prompt-version`.
- **Outputs:** the `--prompt-version` suffix is appended to `--output-dir`, so v1 dirs stay intact as the before/after baseline (e.g. `binary_results_deepseek_chat/` → `_v2/`).

This package lives under `eval_v3-1_claim2action/` (hyphen ⇒ not an importable
module), so `run_stage2.py` is invoked **as a script** (it bootstraps its own
dir + the repo root onto `sys.path`):

```bash
# deepseek-chat (Stage-1 relocated by the reorg), v2 prompt, deepseek-v4-pro judge:
python research/eval_v3-1_claim2action/stage2/run_stage2.py \
  --prompt-version v2 --model deepseek-v4-pro \
  --stage1-dir eval_v3-1_claim2action/stage1/results_deepseek_chat \
  --output-dir binary_results_deepseek_chat

# gpt-4o (Stage-1 still under eval_v3, trajectories under experiments_v2 top-level):
python research/eval_v3-1_claim2action/stage2/run_stage2.py \
  --prompt-version v2 --model deepseek-v4-pro \
  --stage1-dir eval_v3/stage1/results_gpt4o \
  --ind-dir experiments_v2/independent --dep-dir experiments_v2/dependent \
  --traj-suffix _openai_gpt_4o --output-dir binary_results_gpt4o
```

Or run both via `run_v2_batch.sh` (tmux-friendly).

| Version | Contents | routing | output suffix |
| ------- | -------- | ------- | ------------- |
| v1 | baseline | v1 | (none) |
| v2 | Cat 1 + Cat 2 + Cat 3 (below) | v2 | `_v2` |

---

## Metrics methodology (fill the blanks after the v2 run)

1. **Targeted correction rate** — of the v1-mislabeled claims v2 targets
   (tables below), how many now carry the intended verdict. Diff the new
   `*_v2/.../*_verdicts.jsonl` against the `v1 verdict` column here.
2. **Held-out regression check** — judge accuracy vs gold on the reserved
   set **C-1 / D-5 / H-2** (never used as few-shot), plus global NS / NBC
   rates.

`Δ vs v1` = metric(v2) − metric(v1).

> **Judge-model caveat.** v2 is judged by **deepseek-v4-pro** (the
> gemini-3.1-pro Portkey key expired). The v1 verdicts recorded below were
> observed under **gemini-3.1-pro-preview**. The per-category *targeted-flip*
> tables stay informative (did the claim land on the intended verdict under
> the v2 prompt?), but the *overall* held-out-accuracy Δ is judge-confounded —
> do not report it as a pure prompt effect. For a clean prompt-only Δ,
> re-judge v1 with deepseek-v4-pro (or re-run v2 with a fresh gemini key).

### Overall

**v2 run status (2026-06-08, judge = deepseek-v4-pro):**
- **deepseek-chat author — COMPLETE & clean** (95 trajectories):
  `supported 2606, not_supported 167, needs_broader_context 22, parse_error 21, api_error 0`.
- **gpt-4o author — INCOMPLETE**: the DeepSeek API balance was exhausted
  mid-run (`402 Insufficient Balance`); 337/368 claims errored. Re-run with
  `--overwrite` after topping up the account (75 contaminated files).

| Metric | v1 | v2 (deepseek-chat author) | Δ vs v1 |
| ------ | -- | ------------------------- | ------- |
| Held-out accuracy (C-1/D-5/H-2) | ____ | ____ | ____ |
| `not_supported` rate (all claims) | ____ | 5.9% (167/2816) | ____ |
| `needs_broader_context` rate | ____ | 0.8% (22/2816) | ____ |
| Targeted claims corrected | — | **14 / 14** ✅ | — |

> Targeted = the 14 claims in the per-category tables below; **all 14
> flipped to the intended verdict** under v2. `v1` column + held-out
> accuracy still need the gold-scored comparison (and the gpt-4o re-run);
> recall the judge-model caveat above when reading any v1→v2 Δ. The 21
> `parse_error`s are malformed judge JSON (re-runnable), unrelated to the
> prompt fixes.

---

## What changed in v2 (files)

- `propmt_template.md`: `## Task Header` → `## Task Requirement`; channel
  enum gains `task_requirement`, `claim_context`.
- `action_validation_guideline.md`: "Task Requirement (always available)"
  subsection (Cat 3); `action_intention` rules restructured into **Path A**
  (executed), **Path B** (info verification, Cat 2), **Path C**
  (confirmation-deferred, Cat 1), with the abandonment discriminator.
- `preprocess.py` (`routing_version="v2"`): `action_intention` also routes
  previous-step `tool_results` (Path B) and `claim_context` (Path C).
- `few_shot/stage2_examples.md`: corrective examples **CE1** (Cat 3),
  **CE2** (Cat 2), **CE3** (Cat 1) — from non-held-out tasks (M-2, M-3,
  M-5, C-5; never C-1 / D-5 / H-2).

v1 verdicts below were read from the gemini-judged baseline
(`…/binary_results*/…_gemini-pro_v1_verdicts.jsonl`). `claim_id` shown as
its `S<step>-C<idx>` suffix.

---

### Cat 1 — action_intention deferred pending user confirmation (Path C)

Single-turn benchmark: the agent presents a write plan and stops for
confirmation it can never receive (M-5: "Here's what I propose to do …
**Shall I proceed with this update?**"). v1 marked every sub-intention
`not_supported`. Fix: Path C reads `claim_context`; a deferred planned
write is `supported`, content verified against prior `tool_results`.

| claim_id | task | claim span | v1 verdict | intended v2 | actual v2 |
| -------- | ---- | ---------- | ---------- | ----------- | --------- |
| `…S3-C6` | M-5 | "I'll create a new BOM version rather than overwriting the active one." | `not_supported` | `supported` | ✅ `supported` |
| `…S3-C8` | M-5 | "Create a new BOM version (BOM-002) … with these components:" | `not_supported` | `supported` | ✅ `supported` |
| `…S3-C9` | M-5 | "1. Samsung Galaxy S24 (product ID 5) — qty 1" | `not_supported` | `supported` | ✅ `supported` |
| `…S3-C10` | M-5 | "2. USB-C Fast Charger 25W (product ID 12) — qty 1" | `needs_broader_context` | `supported` | ✅ `supported` |
| `…S3-C11` | M-5 | "3. USB-C Charging Cable 2m (product ID 10) — qty 1 (replacing the 1m cable)" | `not_supported` | `supported` | ✅ `supported` |
| `…S3-C12` | M-5 | "set it as the active BOM" | `not_supported` | `supported` | ✅ `supported` |
| `…S3-C13` | M-5 | "while archiving the old one." | `not_supported` | `supported` | ✅ `supported` |

Scope caveat: Path C treats confirmation-seeking as legitimate under the
single-turn design; if a write *without* confirmation would violate
policy, that surfaces on a separate `constraint_or_policy` row — do not
double-penalize on the deferred `action_intention`.

---

### Cat 2 — action_intention satisfied by information already in hand (Path B)

Intent to *verify / check / re-examine* data a previous step already
returned was marked `not_supported` (judge only saw `tool_calls`). Fix:
Path B routes previous-steps `tool_results`; confirming asserted info in
hand needs no new call. Abandoned intents (E2) stay `not_supported`.

| claim_id | task / pair | claim span | v1 verdict | intended v2 | actual v2 |
| -------- | ----------- | ---------- | ---------- | ----------- | --------- |
| `…S2-C1` | C-5 / C1_C5 | "Let me verify the customer details" | `not_supported` | `supported` | ✅ `supported` |
| `…S2-C2` | C-5 / C1_C5 | "check stock availability" | `not_supported` | `supported` | ✅ `supported` |
| `…S8-C9` | M-3 / M1_M5 | "look more closely at the component moves…" | `not_supported` | `supported` | ✅ `supported` |
| `…S8-C23` | M-3 / M1_M5 | "check which location this production order is associated with" | `not_supported` | `supported` (review¹) | ✅ `supported` |
| `…S12-C5` | M-3 / M1_M5 | "re-examine the component availability more carefully" | `not_supported` | `supported` | ✅ `supported` |
| `…S12-C12` | M-3 / M1_M5 | "check if the system considers this order ready" | `not_supported` | `supported` (review¹) | ✅ `supported` |

¹ borders on requesting data not strictly in prior results; if it stays
`not_supported`, that is correct, not a Path-B miss — record and note.

---

### Cat 3 — observation verified against the Task Requirement

An `observation` restating the task request or a date derived from
`current_datetime` was returned `needs_broader_context`, though the task
header is in every prompt. Fix: renamed to **Task Requirement**, made it a
citable channel; such observations are `supported`.

| claim_id | task / pair | claim span | v1 verdict | intended v2 | actual v2 |
| -------- | ----------- | ---------- | ---------- | ----------- | --------- |
| `…S15-C23` | M-2 / M1_M5 | "Requested: 5 units for next Monday (2026-05-11)" | `needs_broader_context` | `supported` | ✅ `supported` |

Known-unaddressed (do not count): M-2 `…S15-C19` "Let me report this to
you." is a Stage-1 over-extraction of vague transition text, expected to
remain flagged.
