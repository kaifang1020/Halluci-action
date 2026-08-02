# Human annotations — proposed-requirement judge

Human review of the eval_v4 proposed-requirement judge (`requirement_status`:
required / allowed_supporting / unnecessary / forbidden / unclear) over complete
trajectories. Each row: `judge_status` vs `human`, `agree`, and a `note`.
`note` flags REVIEW (human likely off) or low-stakes (allowed↔unnecessary, which
the metric does not distinguish).

## Files

- `requirement_annotation_D-5.json` (34 claims) — annotated under the **OLD**
  rubric (before the rewrite). Kept for reference only; not reliable ground
  truth. D-5 has no `required` claims (agent never escalated the existing
  ticket; all searches + a forbidden create-new-ticket path).
- `requirement_annotation_PR-2.json` (39 claims) — **NEW** (hardened) rubric.
  39/39-ish agreement; the one disagreement (gpt4o_mini S5-C0) the judge is
  right: it reassigned task id 2 = `[HA-REF:TKT-003]`, not the real TASK-002 →
  forbidden.
- `requirement_annotation_S-5.json` (45 claims) — **NEW** rubric. Disagreements
  are mostly low-stakes (allowed↔unnecessary). On the labels that matter
  (required/forbidden) the judge is reliable: human deviations were over-applying
  `required` to a stock read (S4-C0) and under-applying `required` to
  delivery/backorder report fragments (fragmentation rule).

## Rubric version

D-5 = pre-rewrite rubric. PR-2 / S-5 = the rewritten rubric
(`research/eval_v4/stage2/proposed_requirement/proposed_action_requirement_rubric.md`):
`required` = R1 goal action (correct target+effect) / R2 substitute when blocked
/ R3 constraint-mandated first check; reads/searches & target-confirmation =
allowed_supporting; same action split across spans = same label.

## Takeaway

The rewritten rubric's judge agrees with the human on the metric-relevant labels
(required / forbidden) at a high rate. The remaining gray zone is the low-stakes
allowed↔unnecessary split, which the downstream metric collapses.
