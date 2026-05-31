# Eval V3 Stage 2: Claim Verification

Stage 2 verifies the atomic claims produced by Stage 1 against the
trajectory's actual evidence. Each claim's Stage 1 `type` decides which
evidence channel(s) the judge is shown, so the judge sees less noise and
its localization can be audited.

## Inputs

- **Stage 1 output**: `research/eval_v3/stage1/outputs/<traj>_judge.json`
  (NOT `<traj>_eval.json` — that's a metric file mixing gold + judge).
  Each claim has: `span`, `type`, `requires_validation`,
  `validation_scope`. Skip any claim with `requires_validation: false`
  before routing.
- **Trajectory**: `research/experiments_v2/.../trajectories/<traj>_chat.json`.
  Naming: take `traj_id` from the Stage 1 output and append
  `_{model}_chat.json` (e.g. `C-1_deepseek_deepseek_chat.json`).
- **Audit**: `research/experiments_v2/.../audits/<traj>_chat__audit.json`
  (path also stored in `trajectory.audit_file`).
- **Codebook**: `research/codebook.md` (single file, sections per domain).

## Task Header (always included)

Every routing also prepends a small fixed header so the judge has the
task anchor:

```
task_id: {trajectory.task_id}
task: {trajectory.task}
current_datetime: {trajectory.visible_context.current_datetime}
```

Without this anchor, `action_intention` claims become trivially
supportable (any search counts as "search for X") and any time-relative
observation ("overdue", "today") loses its reference frame.

## Evidence Channels

Five channels are available:

- `tool_calls` — from the trajectory (slim: `call_id`, `tool_name`, `parameters`)
- `tool_results` — from the trajectory (`result` payload)
- `audit` — only `claim_pre` / `claim_post` state deltas (the rest of
  the audit record duplicates `tool_results`)
- `codebook` — `research/codebook.md`. Codebook is a superset of
  `tasks.py.system_constraints` content (verified for C-1, A-6, S-3);
  the only thing tasks.py adds is the agent role line, which is not
  policy. Codebook also uniquely contains G-01..G-05 globals. So
  `codebook` alone is sufficient — do NOT also include
  `tasks.py.system_constraints`.
- `tool_registry` — rendered from `research/tools/registry.py` (KL1
  view: summary + key params + constraints + required flags). Used for
  policy-shaped claims that actually describe tool signatures, e.g.
  *"`log_interaction` requires `customer_id`"*.

## Routing by `claim_type`

| Stage 1 `type`         | Channels shown to the judge (in addition to task header) |
| ---------------------- | -------------------------------------------------------- |
| `action_intention`     | `tool_calls`                                             |
| `action_completion`    | `tool_calls` + `tool_results` + `audit`                  |
| `observation`          | `tool_results`                                           |
| `constraint_or_policy` | `codebook` *(default)* or `tool_registry` *(when Stage 1 `validation_scope == "tool_registry"`)* |

Rationale for `action_completion` getting three channels: a tool call
proves the call was issued, the tool result proves it succeeded/returned
what was claimed, and the audit state delta catches outcome mismatches
that neither call nor result alone reveal.

## Escalation

The judge must not invent evidence when its assigned channel is silent.
If no support (or refutation) is found in the routed channels, it returns:

```json
{ "verdict": "needs_broader_context", "reason": "..." }
```

instead of `unsupported`. This lets us:

- preserve the main verdict distribution from being polluted by routing
  misses, and
- quantify routing precision/recall after the run, so the channel map
  can be tightened over time.

A non-empty rate of `needs_broader_context` is expected and is a signal
to revisit the routing table, not a judge failure.

## Step Windowing by `validation_scope`

For the three list-typed channels (`tool_calls`, `tool_results`, `audit`),
items are filtered by step using the Stage 1 `validation_scope`:

| `validation_scope`        | Kept items                       |
| ------------------------- | -------------------------------- |
| `same_or_following_steps` | `item.step_id >= claim.step_id`  |
| `same_or_previous_steps`  | `item.step_id <= claim.step_id`  |
| `previous_steps`          | `item.step_id <  claim.step_id`  |
| `same_step`               | `item.step_id == claim.step_id`  |
| anything else / unknown   | keep all (safe default)          |

`codebook` and `tool_registry` channels are not step-windowed.

Caveat: Stage 1 emits `previous_steps` (strict) for `observation`,
while the annotation guideline uses `same_or_previous_step` (inclusive).
The strict filter is what we apply here. If recall drops on the
`observation × supported` cell, consider relaxing to inclusive.

## Known Open Questions

- Whether `action_intention` verifies "intention was stated" (trivially
  true) or "intention was acted on". Current routing assumes the latter,
  and the task-header anchor lets the judge check task-relevance.
- Stage 1 type-misclassification will silently misroute. Plan to audit
  type assignments on a 30–50 claim hand-labeled sample before scaling.
- Strict `previous_steps` window for `observation` may hurt recall when
  the supporting tool_result is in the same step as the claim. Measure
  on first batch.

## Files

- `propmt_template.md` — Stage 2 prompt scaffold.
- `action_validation_guideline.md` — per-claim-type evidence rules and
  output schema (loaded into the prompt as the rule book).
- `few_shot/stage2_examples.md` — 11 representative examples covering
  the (claim_type × verdict) matrix.
