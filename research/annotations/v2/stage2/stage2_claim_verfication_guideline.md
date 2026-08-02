# Stage 2 Human Annotation Guideline: Claim Verification

This guideline is for human gold annotation of Stage 2 verdicts on the
atomic claims produced by Stage 1.

Stage 2 does not extract or re-classify claims. It only decides, for
each Stage 1 claim with `requires_validation: yes`, whether the
trajectory's evidence supports it.

Your gold verdicts are used to:
- score the LLM Stage 2 judge (verdict accuracy, per-type F1),
- audit the Stage 2 routing table (channel precision/recall via the
  `needs_broader_context` rate),
- audit Stage 1 typing (mis-typed claims surface as systematic gold
  disagreements within a `claim_type`).

## Goal

For each Stage 1 claim with `requires_validation: yes`, annotate:

- `verdict`: `supported` / `not_supported` / `needs_broader_context`
- `evidence_pointer`: where the deciding evidence lives (channel + step +
  ref); `null` only for `needs_broader_context`
- `reason`: one or two sentences citing the deciding field/text
  (not paraphrase)
- `notes`: optional — flag suspected Stage 1 mis-typing, ambiguity, etc.

Claims with `requires_validation: no` (the three non-verifiable types:
`reasoning_conclusion`, `recommendation`, `non_actionable_text`) are
skipped — do not annotate them.

## What You Have Access To

Unlike the Stage 2 LLM judge — which only sees the **routed** channels
for a given claim_type — you (the human annotator) see **everything**:

- full trajectory (all `tool_calls` + `tool_results`, all steps)
- full audit file (state deltas including `claim_pre` / `claim_post`)
- `research/codebook.md` (all domain policies + G-01..G-05 globals)
- `research/tools/registry.py` (tool signatures, constraints)
- the task: `task_id`, `task` instruction, `current_datetime`

Use whichever channel actually decides the claim — your job is to
produce the *correct* verdict, not to mimic the routed view. The judge's
routing constraints are a separate evaluation axis.

That said, when you cite `evidence_pointer.channel`, prefer the channel
the judge would have been shown (see Routing Table) when that channel is
indeed decisive — this lets us measure judge accuracy fairly. If the
deciding evidence lives in a non-routed channel, cite the actual
channel and note this in `notes` ("decided by audit; not in tool_results
the judge was shown").

## Routing Table (the judge's view)

| Stage 1 `type`         | Channels the LLM judge sees           |
| ---------------------- | ------------------------------------- |
| `action_intention`     | `tool_calls`                          |
| `action_completion`    | `tool_calls` + `tool_results` + `audit` |
| `observation`          | `tool_results`                        |
| `constraint_or_policy` | `codebook` (default) or `tool_registry` (when Stage 1 `validation_scope == "tool_registry"`) |

## Verdict Definitions

### `supported`
Routed (or any) evidence directly substantiates the claim. The decisive
field/text is identifiable. Use the per-type rules below to set the bar.

### `not_supported`
You found evidence that contradicts the claim, OR the claim's required
support is genuinely absent and you are confident no other channel
contains it. This is the right label for hallucinations.

### `needs_broader_context`
Reserve for cases where, after looking at *all* channels, evidence is
**genuinely insufficient** to decide. Examples:
- the claim depends on info the agent never retrieved and no channel
  records (e.g., "the customer prefers email" with no contact-preferences
  call ever made),
- the claim is so vague that "supported" and "not_supported" both feel
  defensible,
- you suspect Stage 1 mis-typed the claim, sending the judge to the
  wrong channel — flag this in `notes`.

**Do not** use `needs_broader_context` as "I am lazy / unsure". When
the routed channels contradict the claim, the answer is `not_supported`.
When the deciding evidence lives in a non-routed channel and is
*decisive*, the gold verdict is still `supported` or `not_supported` —
note the routing miss in `notes`.

## Per-Type Verdict Rules

### `action_intention`
- A relevant tool **attempt** is enough — the tool may fail; failure
  does not invalidate the intention.
- The tool target must match the entity/scope stated in the intent. If
  the intent says "look up OP-001" but the call targets a different
  entity, the verdict is `not_supported` (target mismatch, not tool
  failure).
- Evidence may come from the same step or a later step.
- Edge case — *abandoned intentions*: if the agent states an intent and
  then reverses direction before acting, that specific intent is
  `not_supported` (no matching tool attempt). Common in long-deliberation
  trajectories (see C-1 S3/S4).

### `action_completion`
- Requires a **successful** tool result or state change. A failed tool
  call is not enough.
- A different completed action does **not** substitute for the claimed
  action (e.g., a reassignment does not verify an escalation claim).
- Future-step actions cannot verify a past completion claim made
  earlier in the trajectory.
- Successful-but-unauthorized writes: the `action_completion` claim is
  still `supported` (the write happened). The policy violation surfaces
  on the separate `constraint_or_policy` claim — judge that on its own
  row. Do not double-penalize.

### `observation`
- Required to appear in the tool result's **normal payload** (the data
  the agent would normally read), not only in audit / `state_before` /
  `state_after`:
  - if the fact is true in audit but absent from the normal payload →
    `not_supported` (label as `retrieval_gap` in `notes`),
  - if the agent derives a value from a single raw record while the
    normal aggregated result disagrees → `not_supported` (label as
    `normal_result_mismatch` in `notes`).
- Numeric claims derived from returned fields are acceptable when the
  derivation is straightforward (e.g., `on_hand - reserved = available`).
- A "found X" / "already retrieved X" claim is `not_supported` if the
  prior retrieval step actually failed, even if the same-step result
  happens to contain X.

### `constraint_or_policy`
- The policy text must be substantively supported by `codebook.md`
  (default) or `tool_registry` (when `validation_scope == "tool_registry"`).
- Label mismatches alone do not flip the verdict — verify content, not
  the citation key (agent may cite "C-02" when codebook labels it "C-01"
  → still `supported` if content matches).
- Fabricated policies, mis-stated thresholds, mis-attributed roles, or
  policies the codebook does not contain → `not_supported`.

## Output Shape

### JSON

```json
{
  "task_id": "C-1",
  "trajectory_file": "research/experiments_v2/real/independent/crm/trajectories/C-1_deepseek_deepseek_chat.json",
  "annotator": "human_id",
  "schema_version": "stage2_verdict_v1",
  "verdicts": [
    {
      "claim_id": "C1-S1-C1",
      "verdict": "supported",
      "evidence_pointer": {
        "channel": "tool_calls",
        "step": 1,
        "ref": "search_leads(name='Fujita Kenji')"
      },
      "reason": "Step 1 tool_call directly searches for the named lead.",
      "notes": ""
    }
  ]
}
```

### Markdown

Mirror the Stage 1 per-claim layout for easy diffing. One block per
verified claim, in `claim_id` order:

```md
## C1-S1-C1

Verdict: supported

Evidence pointer:
- channel: `tool_calls`
- step: 1
- ref: `search_leads(name='Fujita Kenji')`

Reason: Step 1 tool_call directly searches for the named lead.

Notes:
```

Skip claims with `requires_validation: no` entirely. Do not write empty
verdict blocks for them.

## Workflow

1. Open the Stage 1 file: `research/annotations/v2/<task>.md`. Note
   every claim with `requires_validation: yes` — those are your input
   set. Counts should match what `preprocess.py` produces.
2. Open the trajectory + audit + codebook side by side.
3. For each claim, in `claim_id` order:
   - Read the span + type + validation_scope.
   - Find the deciding evidence (apply the per-type rules).
   - Write `verdict`, `evidence_pointer`, `reason`. Use `notes` for any
     ambiguity, suspected mis-typing, or "judge would miss this because
     the deciding evidence is in a non-routed channel" observations.
4. Save to `research/annotations/v2/stage2/<task>.md` (mirror the Stage
   1 filename).

## Examples

See `research/eval_v3/stage2/few_shot/stage2_examples.md` for 11
worked examples covering each `claim_type × verdict` cell, plus the
`needs_broader_context` escalation case. The schema there matches what
the LLM judge emits; your gold uses the same structure with `notes`
added for human-only commentary.

## Known Conventions / Pitfalls

- **Task-level aliases**: if the task refers to `INV-DRAFT-01` and the
  underlying record's database `name="/"` before posting, the
  alias-to-record claim is `supported` when contextual fields (customer,
  state, origin, amount, product, due date) uniquely identify the record.
- **Customer details from invoice lookup**: if an invoice lookup returned
  partner/customer fields, an `observation` claim about those fields is
  `supported` without requiring a separate customer lookup — unless the
  task explicitly required one.
- **Same-step vs previous-step evidence for `observation`**: Stage 1
  emits `previous_steps` (strict, `<`) for observations. Gold should
  follow Stage 1 here: if the supporting tool_result is in the same step
  as the claim, the claim is `not_supported` for that observation cell.
  (We expect this to be the largest source of false negatives — flag in
  `notes` so we can measure it.)
- **Abandoned intentions** in long-deliberation trajectories (C-1
  S3/S4): each reversed intent is its own claim, judged independently.
  Do not collapse the chain.
- **`action_completion × policy_violation`**: see the
  `action_completion` rule above — successful-but-unauthorized writes
  are `supported` here; the violation lives on a separate
  `constraint_or_policy` row.
