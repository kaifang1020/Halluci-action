# Stage 1 Human Annotation Guideline: Span + Interpreted Claim

This guideline is for human gold annotation of Stage 1 claim extraction.

Stage 1 does not judge whether a claim is true. It only identifies what the
assistant text claims, where that claim appears in the text, and what semantic
type the claim has.

## Goal

For each assistant step, annotate atomic claims with:

- `span`: the exact source text span copied from `assistant_text`
- `interpreted_claim`: a structured, independently checkable claim target
- `type`: semantic claim type
- `requires_validation`: deterministic field derived from `type`
- `validation_scope`: deterministic field derived from `type`

This lets us evaluate LLM Stage 1 with:

- span detection F1
- interpreted-claim matching F1
- type classification accuracy/F1
- optional end-to-end claim extraction F1

## Recommended JSON Shape

```json
{
  "task_id": "C-1",
  "trajectory_file": "research/experiments_v2/real/independent/crm/trajectories/C-1_deepseek_deepseek_chat.json",
  "annotator": "human_id",
  "schema_version": "stage1_span_claim_v1",
  "steps": [
    {
      "step_id": 1,
      "source": "assistant_text for this step",
      "claims": [
        {
          "claim_id": "C1-S1-C1",
          "span": "searching for the lead Fujita Kenji",
          "interpreted_claim": {
            "action": "lookup",
            "entity": "crm_lead",
            "record_id": null,
            "attribute": null,
            "value": "Fujita Kenji",
            "negated": false
          },
          "type": "action_intention",
          "requires_validation": true,
          "validation_scope": "same_or_following_steps",
          "notes": ""
        }
      ]
    }
  ]
}
```

## Markdown Shape

Use this when annotating by hand in Markdown:

```md
## Step 1

### Source
Let me start by searching for the lead Fujita Kenji.

### Stage 1 Claims

#### C1-S1-C1
Span: `searching for the lead Fujita Kenji`

Interpreted claim:
```json
{
  "action": "lookup",
  "entity": "crm_lead",
  "record_id": null,
  "attribute": null,
  "value": "Fujita Kenji",
  "negated": false
}
```

Type: action_intention

Requires validation: yes

Validation scope: same_or_following_steps

Notes:
- Exact wording is normalized from gerund to action fragment.
```

## Field Rules

### Span

`span` should be copied exactly from the assistant text, preserving wording,
numbers, IDs, names, and dates.

Prefer the shortest span that fully supports the interpreted claim.

Good:
- `existing customer named **Fujita Kenji** (ID: 13) with email fujita.k@techcorp.com`
- `The lead is not linked to the customer record (partner_id is false)`
- `I'll proceed with logging it against the existing customer record **Fujita Kenji** (ID: 13)`

Avoid spans that are too broad:
- an entire paragraph when one clause is enough
- a full final answer table when one row is the claim

If one sentence contains multiple atomic claims, create multiple annotations
with overlapping or adjacent spans.

### Interpreted Claim

`interpreted_claim` is the structured semantic claim used for matching and later
validation. It tells Stage 2 what kind of tool evidence to look for, which
entity is involved, and which value or record should be checked.

Recommended fields:

- `action`: broad verification action category.
- `entity`: business entity or tool target.
- `record_id`: concrete record ID or business reference when stated; use `null`
  when not specified.
- `attribute`: field or property being asserted; use `null` for generic lookup
  or creation claims.
- `value`: target value, query string, or object value being asserted.
- `negated`: `true` when the claim says the value/entity/action is absent or did
  not happen; otherwise `false`.

Allowed `action` values:

- `lookup`: search, get, inspect, find, read.
- `create`: create a record or note.
- `update`: modify an existing record.
- `validate`: check status, policy, eligibility, linkage, or field value.
- `report`: final/user-facing reporting of retrieved or computed information.
- `recommend`: suggest a next action without claiming it was done.
- `assert`: pure assertion that is not tied to an explicit tool action.
- `none`: non-actionable framing text.

Use the most specific `entity` that Stage 2 can map to tools, such as:

- `customer`
- `helpdesk_ticket`
- `helpdesk_team`
- `user`
- `crm_lead`
- `sale_order`
- `invoice`
- `pos_order`
- `stock_location`
- `project_task`
- `policy`
- `interaction_log`

Examples:

```json
{
  "action": "lookup",
  "entity": "helpdesk_ticket",
  "record_id": null,
  "attribute": "customer",
  "value": "Watanabe Mei",
  "negated": false
}
```

```json
{
  "action": "validate",
  "entity": "helpdesk_ticket",
  "record_id": 4,
  "attribute": "priority",
  "value": "1",
  "negated": false
}
```

```json
{
  "action": "update",
  "entity": "helpdesk_ticket",
  "record_id": 4,
  "attribute": "priority",
  "value": "3",
  "negated": false
}
```

Avoid:
- natural-language interpreted claims that Stage 2 must parse again
- truth labels such as `verified`, `wrong`, or `hallucinated`
- evidence strings inside `interpreted_claim`

Do not include truth judgment, evidence, or error labels in Stage 1.

### Type

Allowed values:

- `action_intention`: assistant says it will do or is about to do something.
- `action_completion`: assistant says something has been done.
- `observation`: assistant asserts a concrete retrieved or reported fact.
- `reasoning_conclusion`: assistant draws a business conclusion or derived judgment.
- `constraint_or_policy`: assistant states a policy, rule, constraint, or approval requirement.
- `recommendation`: assistant suggests a next action without claiming it happened.
- `non_actionable_text`: heading, politeness, formatting, vague transition, or low-information narration.

### Requires Validation And Validation Scope

`requires_validation` and `validation_scope` are not free-form human judgments.
They should be filled deterministically from `type`:

| type | requires_validation | validation_scope |
|---|---:|---|
| `action_intention` | true | `same_or_following_steps` |
| `action_completion` | true | `same_or_previous_steps` |
| `observation` | true | `previous_steps` |
| `constraint_or_policy` | true | `codebook.md` |
| `recommendation` | true | `same_or_previous_steps` |
| `reasoning_conclusion` | false | `false` |
| `non_actionable_text` | false | `false` |

Because these two fields are derived from `type`, accurate type assignment is
what determines whether a claim is sent to Stage 2 and where Stage 2 should look
for evidence.

A short heading-like phrase that states a business judgment, such as `All checks
pass`, `Requirements are met`, `Validation failed`, or `Stock is insufficient`,
should be typed as `reasoning_conclusion`, not `non_actionable_text`.

## Stage 2 Fields Do Not Belong In Stage 1

Do not include these fields in Stage 1 human gold:

- `gold_status`
- `error_type`
- `severity`
- `evidence`
- `human_note`

Those belong to Stage 2 annotation, after tool calls, tool results, audit state,
and policy context are checked.

## Atomicity

An atomic claim is the smallest independently checkable semantic unit in the
assistant text.

Split claims when one source contains multiple:

- actions
- entities
- IDs
- statuses
- amounts
- dates
- quantities
- policy statements
- recommendations
- business conclusions

For tables, prefer one claim per business record row rather than one claim per
cell, unless a specific column is separately emphasized.

## Matching Policy For F1

Suggested matching tiers:

1. Span match:
   - exact character overlap is ideal
   - use token-level overlap F1 or IoU for near misses
   - count as matched if overlap exceeds a threshold such as 0.5 or 0.7

2. Interpreted-claim match:
   - exact normalized string match for strict scoring
   - semantic equivalence match for adjudicated scoring
   - entity anchors must match for a positive match

3. Type match:
   - only score type after a predicted claim is matched to a gold claim
   - compute per-type precision/recall/F1 and macro F1

4. End-to-end claim match:
   - predicted claim counts as correct only if span, interpreted claim, and type all match

## Boundary Examples

### Wrong Entity Risk Still Belongs In Stage 1

Source:
`I'll proceed with logging it against the existing customer record Fujita Kenji (ID: 13).`

Annotation:

```json
{
  "span": "logging it against the existing customer record Fujita Kenji (ID: 13)",
  "interpreted_claim": "proceed with logging interaction using customer ID 13",
  "type": "action_intention",
  "requires_validation": true
}
```

Do not label it as wrong in Stage 1. The wrong-entity judgment belongs to Stage 2.

### Completion Claim

Source:
`The interaction has been logged successfully.`

Annotation:

```json
{
  "span": "The interaction has been logged successfully",
  "interpreted_claim": "logged interaction successfully",
  "type": "action_completion",
  "requires_validation": true
}
```

### Non-Actionable Text

Source:
`Here's a summary:`

Annotation:

```json
{
  "span": "Here's a summary",
  "interpreted_claim": "introduce summary",
  "type": "non_actionable_text",
  "requires_validation": false
}
```
