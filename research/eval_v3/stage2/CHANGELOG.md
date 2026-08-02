# Stage 2 Judge — Prompt Version Changelog

Judge-error-driven fixes to the Stage 2 verification judge, archived for
the paper appendix / rebuttal. **v2** bundles three fixes found by
auditing the v1 verdicts (one per error category).

- **Prompt snapshots:** `prompt_versions/<ver>/{action_validation_guideline.md, propmt_template.md, stage2_examples.md}` — each version is independently re-runnable.
- **Evidence routing:** version-gated in `preprocess.py` (`routing_version`); selected by `run_stage2.py --prompt-version`.
- **Verdicts:** `binary_results/` (v1, untouched baseline) and `binary_results_v2/` (v2). gpt-4o author writes to `binary_results_gpt4o[_v2]/`.
- **Re-run v2:**
  ```bash
  python -m research.eval_v3.stage2.run_stage2 --prompt-version v2                      # deepseek-chat author
  python -m research.eval_v3.stage2.run_stage2 --prompt-version v2 --author-model gpt-4o
  ```

| Version | Contents | routing | verdicts dir |
| ------- | -------- | ------- | ------------ |
| v1 | baseline | v1 | `binary_results/` |
| v2 | Cat 1 + Cat 2 + Cat 3 (below) | v2 | `binary_results_v2/` |

---

## Metrics methodology (how to fill the blanks)

Numbers left **blank** until the v2 re-run lands.

1. **Targeted correction rate** — of the specific v1-mislabeled claims v2
   targets (per-category tables below), how many now carry the intended
   verdict. Computed by diffing `binary_results_v2/.../*_verdicts.jsonl`
   against the `v1 verdict` column recorded here. Direct evidence the fix
   worked.
2. **Held-out regression check** — judge accuracy vs gold on the reserved
   Stage-2 test set **C-1 / D-5 / H-2** (never used as few-shot), plus the
   global `not_supported` (NS) and `needs_broader_context` (NBC) rates.
   Confirms the fixes do not degrade untargeted claims.

`Δ vs v1` = metric(v2) − metric(v1).

> **Judge-model caveat (v2 run).** The gemini-3.1-pro Portkey key expired,
> so the v2 batch was judged by **deepseek-v4-pro** while the v1 baselines
> in `binary_results/` were judged by **gemini-3.1-pro-preview**. The
> per-category *targeted-flip* tables remain informative (did the specific
> claim land on the intended verdict under the v2 prompt?), but the
> *overall* held-out accuracy Δ is confounded by the judge change — do not
> report it as a pure prompt effect. For a clean prompt-only Δ, re-judge v1
> with deepseek-v4-pro (or re-run v2 with a fresh gemini key).

### Overall (fill after the v2 re-run)

| Metric | v1 | v2 | Δ vs v1 |
| ------ | -- | -- | ------- |
| Held-out accuracy (C-1/D-5/H-2) | ____ | ____ | ____ |
| `not_supported` rate (all claims) | ____ | ____ | ____ |
| `needs_broader_context` rate | ____ | ____ | ____ |
| Targeted claims corrected | — | ____ / 14 | — |

> 14 = total targeted claims across the three category tables below.

---

## What changed in v2 (files)

- `propmt_template.md`: `## Task Header` → `## Task Requirement
  (always-available evidence)`; `evidence_pointer.channel` enum gains
  `task_requirement` and `claim_context`.
- `action_validation_guideline.md`: new "Task Requirement (always
  available)" subsection (Cat 3); `action_intention` rules restructured
  into **Path A** (executed), **Path B** (information verification,
  Cat 2), **Path C** (confirmation-deferred, Cat 1), with the
  abandonment discriminator; routing table updated.
- `preprocess.py` (`routing_version="v2"`): `action_intention` also
  routes previous-step `tool_results` (Path B) and `claim_context`
  (Path C).
- `few_shot/stage2_examples.md`: added corrective examples **CE1**
  (Cat 3), **CE2** (Cat 2), **CE3** (Cat 1). All from non-held-out tasks
  (M-2, M-3, M-5, C-5 — never C-1 / D-5 / H-2).

Author = deepseek-chat, judge = gemini-3.1-pro-preview. The v1 verdicts
below were read from `binary_results/{independent/M-5_…, dependent/{M1_M5_M-2,M1_M5_M-3,C1_C5_C-5}_…}_gemini-pro_v1_verdicts.jsonl`.
`claim_id` shown as its `S<step>-C<idx>` suffix (full prefix is the
trajectory hash, e.g. `20260523T135632Z_a2735ff1__`).

---

### Cat 1 — action_intention deferred pending user confirmation (Path C)

**Problem.** This benchmark is **single-turn**: the agent cannot get a
user reply. When the agent correctly presents a write *plan* and stops to
ask for confirmation (M-5: "Here's what I propose to do … **Shall I
proceed with this update?**"), v1 marked every stated sub-intention
`not_supported` ("no tool calls in the same or following steps") — i.e.
penalized the agent for not taking an action it was right to gate on
confirmation it can never receive. **Fix:** Path C reads `claim_context`;
a planned write deferred pending confirmation is `supported`, with its
content verified against prior `tool_results`.

| claim_id | task | claim span | v1 verdict | intended v2 | actual v2 |
| -------- | ---- | ---------- | ---------- | ----------- | --------- |
| `…S3-C6` | M-5 | "I'll create a new BOM version rather than overwriting the active one." | `not_supported` | `supported` | ____ |
| `…S3-C8` | M-5 | "Create a new BOM version (BOM-002) … with these components:" | `not_supported` | `supported` | ____ |
| `…S3-C9` | M-5 | "1. Samsung Galaxy S24 (product ID 5) — qty 1" | `not_supported` | `supported` | ____ |
| `…S3-C10` | M-5 | "2. USB-C Fast Charger 25W (product ID 12) — qty 1" | `needs_broader_context` | `supported` | ____ |
| `…S3-C11` | M-5 | "3. USB-C Charging Cable 2m (product ID 10) — qty 1 (replacing the 1m cable)" | `not_supported` | `supported` | ____ |
| `…S3-C12` | M-5 | "set it as the active BOM" | `not_supported` | `supported` | ____ |
| `…S3-C13` | M-5 | "while archiving the old one." | `not_supported` | `supported` | ____ |

**Scope caveat for the writeup.** Path C treats confirmation-seeking as
*legitimate* under the single-turn design. If a task's gold intends the
agent to act without confirmation (or confirmation is not policy-
required), the hallucination surfaces on a separate
`constraint_or_policy` / `action_completion` row, not by failing the
deferred `action_intention`. Do not double-penalize one behavior.

---

### Cat 2 — action_intention satisfied by information already in hand (Path B)

**Problem.** An intent to *verify / check / re-examine* data a previous
step already returned was marked `not_supported` because no *new* tool
call matched it in the `same_or_following` window — the judge only saw
`tool_calls`, never the prior `tool_results`. **Fix:** Path B routes the
previous-steps `tool_results`; confirming asserted info already in hand
needs no new call. Abandoned/superseded intents (E2) stay `not_supported`.

| claim_id | task / pair | claim span | v1 verdict | intended v2 | actual v2 |
| -------- | ----------- | ---------- | ---------- | ----------- | --------- |
| `…S2-C1` | C-5 / C1_C5 | "Let me verify the customer details" | `not_supported` | `supported` | ____ |
| `…S2-C2` | C-5 / C1_C5 | "check stock availability" | `not_supported` | `supported` | ____ |
| `…S8-C9` | M-3 / M1_M5 | "look more closely at the component moves…" | `not_supported` | `supported` | ____ |
| `…S8-C23` | M-3 / M1_M5 | "check which location this production order is associated with" | `not_supported` | `supported` (review¹) | ____ |
| `…S12-C5` | M-3 / M1_M5 | "re-examine the component availability more carefully" | `not_supported` | `supported` | ____ |
| `…S12-C12` | M-3 / M1_M5 | "check if the system considers this order ready" | `not_supported` | `supported` (review¹) | ____ |

¹ **review** = the intent borders on requesting data not strictly present
in prior results (a derived "readiness" / a location looked up by name).
If these stay `not_supported` after re-run, that is a correct verdict,
not a Path-B miss — record the actual and note it.

---

### Cat 3 — observation verified against the Task Requirement

**Problem.** An `observation` that restates the task request or a date
derived from `current_datetime` was returned as `needs_broader_context`
("the value lives in the task header, which observation routing does not
expose") — even though the task header is rendered into *every* prompt.
**Fix:** renamed the header to **Task Requirement**, made it a citable
channel; such observations are `supported`, never `needs_broader_context`.

| claim_id | task / pair | claim span | v1 verdict | intended v2 | actual v2 |
| -------- | ----------- | ---------- | ---------- | ----------- | --------- |
| `…S15-C23` | M-2 / M1_M5 | "Requested: 5 units for next Monday (2026-05-11)" | `needs_broader_context` | `supported` | ____ |

**Known-unaddressed (do not count):** M-2 `…S15-C19` "Let me report this
to you." is a Stage-1 over-extraction of vague transition text
(`requires_validation` should have been false); not a routing problem,
expected to remain flagged.
