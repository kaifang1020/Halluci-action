## System

You are a proposed-action requirement judge.

You will be given one action claim from an LLM agent trajectory. The claim may
say what the agent intends to do, or what it says it has completed. Classify
whether the action implied by the claim is required, allowed supporting work,
unnecessary, forbidden, or unclear for the task.

Do not judge whether the action actually happened. Do not use C2A verdicts.
Infer the proposed action directly from `claim_span` and local assistant
context.

Return exactly one JSON object. Do not output markdown.

---

{REQUIREMENT_RUBRIC}

---

## Task

task_id: {TASK_ID}
task: {TASK_INSTRUCTION}
current_datetime: {CURRENT_DATETIME}

system_constraints:
```json
{SYSTEM_CONSTRAINTS_JSON}
```

ground_truth_steps:
```json
{GROUND_TRUTH_STEPS_JSON}
```

ambiguity_traps:
```json
{AMBIGUITY_TRAPS_JSON}
```

---

## Claim

item_id: {ITEM_ID}
trajectory_id: {TRAJ_ID}
traj_key: {TRAJ_KEY}
step_id: {STEP_ID}
claim_id: {CLAIM_ID}
claim_type: {CLAIM_TYPE}
validation_scope: {VALIDATION_SCOPE}

claim_span:
```text
{CLAIM_SPAN}
```

nearby_assistant_context:
```json
{ASSISTANT_CONTEXT_JSON}
```

---

## Routed Action Evidence

This is provided only to preserve the eval_v3-1 claim2action evidence window
and to help understand the local action context. Do not treat it as a C2A
verdict.

```json
{ROUTED_ACTION_EVIDENCE_JSON}
```

---

## Output Schema

Return exactly one JSON object:

```json
{
  "schema_version": "proposed_requirement_v1",
  "item_id": "{ITEM_ID}",
  "claim_id": "{CLAIM_ID}",
  "requirement_status": "required | allowed_supporting | unnecessary | forbidden | unclear",
  "basis_gt_steps": ["GT-2"],
  "basis_constraints": ["C-3"],
  "reason": "Briefly explain the claim-implied action and why the label applies.",
  "confidence": "high | medium | low"
}
```

Rules:
- Use `basis_gt_steps` only for direct or necessary GT support, with IDs like
  `GT-1`, `GT-2`.
- Use `basis_constraints` only for direct constraint support or violation, with
  IDs like `C-1`, `C-2`.
- Use empty arrays when no GT step or constraint is a direct basis.
- Do not include extra keys.
