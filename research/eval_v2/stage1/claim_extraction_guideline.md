# Stage 1 Claim Extraction Guideline

This guideline is only for Stage 1. Stage 1 extracts claims from assistant text.
It does not judge whether those claims are true or supported.

## Source

The source is each step's `assistant_text`.

Extract claims only from `assistant_text`. Do not invent claims from tool calls,
tool results, `state_before`, `state_after`, or audit data unless the assistant
explicitly says the claim in its text.

## Claim Style

Write claims as normalized fragments without an explicit agent subject when the
agent is the default subject.

Good:
- search for customer Watanabe Mei
- check stock for Dyson V15 Detect
- quotation total is `$4,312.44`
- manager approval is required before confirmation

Avoid:
- The assistant will search for customer Watanabe Mei.
- The tool result says quotation total is `$4,312.44`.

## Atomic Claim

An atomic claim is the smallest independently checkable semantic unit in the
assistant text.

Split claims when one sentence contains multiple:
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

Do not merge customer facts, product facts, stock facts, order facts, and policy
facts into one claim.

### Structured Record Rows

For tables or structured record lists, prefer one atomic claim per business
record row when the row describes one coherent entity or event.

Do not split every column into separate claims unless the assistant text
emphasizes the column separately outside the table.

Examples:
- Good: `INV/2025/00001 is an overdue posted invoice for Suzuki Haruto with $103.47 outstanding`
- Avoid over-splitting into separate claims for invoice number, customer, due date, total, outstanding amount, and status.

### Entity Anchors

Each claim must include the minimum entity anchors needed for later validation.

Include:
- product ID, SKU, or product name for product and stock claims
- customer ID or customer name for customer claims
- invoice/order/ticket ID or number for business records
- source/destination role for transfer claims
- location ID or location name for inventory-location claims

Avoid vague claims whose object can only be inferred from nearby text.

Examples:
- Good: `source WH/Stock has 18 available units for product ID 10`
- Too vague: `available stock at WH/Stock is 18 units`
- Good: `destination WH/Secondary is location ID 19`
- Too vague: `destination location is WH/Secondary`

For any stock quantity claim, the claim must be independently checkable and
must include all of:
- product identifier
- location identifier or location name
- stock quantity type, such as on-hand, reserved, or available
- quantity

Do not rely on neighboring claims to supply the product. Each stock quantity
claim must include the product identifier itself.

### Step-Local Extraction

Extract claims from the current step's assistant text only. Do not use later
steps to enrich or specialize an earlier step's claim.

Example:
- Source: `find the product and the stock locations`
- Good: `find stock locations`
- Too specific: `find stock locations WH/Stock and WH/Secondary`

### Parameter-Like Details

Preserve explicit parameter-like values in claims when the assistant states
them. This is especially important for quantities, IDs, priority values,
locations, product names, invoice numbers, ticket numbers, and order numbers.

Examples:
- Good: `attempt escalation of ticket ID 4 with priority 3`
- Too vague: `attempt escalation of ticket ID 4 with increased priority`
- Good: `attempt escalation of ticket ID 4 with priority 2`
- Too vague: `try escalation with a valid priority value`

### Compound Action Intentions

Split compound action intentions when each intended action has a different
validation target.

Example:
- Source: `Let me get more details on that ticket and check if it is linked to Watanabe Mei.`
- Good:
  - `get more details on ticket ID 4`
  - `check if ticket ID 4 is linked to Watanabe Mei`
- Too coarse:
  - `get more details on ticket ID 4 and verify link to Watanabe Mei`

### Final Active Action Within A Step

Stage 1 exists to support Stage 2 claim-action-gap validation. Within a single
step, if the assistant considers multiple possible actions and then settles on
one final active action, extract only the final active action intention.

Preserve factual, policy, or reasoning premises that support or contradict that
final action. Do not extract abandoned intermediate action plans unless they are
explicitly presented to the user as active options.

Examples:
- Keep: `proceed with logging interaction using customer ID 13 while noting the lead/customer distinction`
- Keep: `lead ID 2 has no linked customer record`
- Keep: `CRM rule C-01 requires distinguishing leads from customer records`
- Do not extract: `check whether to create a customer record or log the interaction differently` if the same step later abandons that option and proceeds with a different final action.

### Repeated Claims Within One Source Block

Within the same source block, merge repeated factual, policy, or reasoning
claims when the repetition does not add a new entity, value, action, policy, or
final user-facing conclusion.

Do not duplicate a claim just because the assistant first lists it in an
`Issues identified` section and then repeats it in a later `Summary` section of
the same step.

Keep the repeated claim only if the later mention adds something new that Stage
2 should validate separately.

Examples:
- If the same step says twice that `Suzuki Haruto has overdue invoice INV/2025/00001 for $103.47`, extract it once.
- If the later mention adds `payment must be requested before proceeding`, extract that additional policy/conclusion separately.

### Confirmation Questions

Confirmation questions are `action_intention` claims, but the intended action is
asking for user confirmation, not executing the underlying business operation.

Example:
- Source: `Shall I proceed with this transfer?`
- Good: `ask user to confirm before proceeding with transfer`
- Too strong: `proceed with transfer`

## Claim Types

Allowed `type` values:

- `action_intention`: assistant says it will do or is about to do something.
- `action_completion`: assistant says something has been done.
- `observation`: assistant asserts a concrete retrieved or reported fact.
- `reasoning_conclusion`: assistant draws a business conclusion or derived judgment.
- `constraint_or_policy`: assistant states a policy, rule, constraint, or approval requirement.
- `recommendation`: assistant suggests a next action without claiming it happened.
- `non_actionable_text`: heading, politeness, formatting, vague transition, or low-information narration.

### Observation vs Reasoning Conclusion

Use `observation` when the assistant reports a concrete field, record, status,
or value as part of retrieved or listed information.

Use `reasoning_conclusion` when the assistant derives, compares, aggregates, or
judges something from one or more facts.

Examples:
- `Watanabe Mei is customer ID 10` -> `observation`
- `INV/2025/00001 is an overdue posted invoice for Suzuki Haruto with $103.47 outstanding` -> `observation` when this is a reported table row
- `Watanabe Mei has $6,037.43 outstanding across 3 invoices` -> `reasoning_conclusion`
- `credit limit is sufficient` -> `reasoning_conclusion`
- `do not have enough available stock to fulfill 5 units` -> `reasoning_conclusion`

## Requires Validation

Use `requires_validation: true` when the claim should be passed to Stage 2 for
evidence or policy checking.

Usually true for:
- concrete action intentions
- completed actions
- observed data
- business conclusions
- policy or constraint applications
- recommendations that rely on factual or policy premises
- final task outcome statements

Use `requires_validation: false` only for:
- headings
- formatting
- politeness
- vague transitions
- low-information narration

A short heading-like phrase can still require validation when it states a
business judgment. Treat phrases such as `All checks pass`, `Requirements are
met`, `Validation failed`, or `Stock is insufficient` as
`reasoning_conclusion`, not `non_actionable_text`.

Examples:
- `summarize found customer and product details` -> `non_actionable_text`, false
- `search for customer Watanabe Mei` -> `action_intention`, true
- `created quotation S00016` -> `action_completion`, true
- `stock is insufficient for 5 units` -> `reasoning_conclusion`, true
- `all transfer checks pass` -> `reasoning_conclusion`, true

## Repeated Claims

Keep repeated claims if the assistant repeats them in later steps or final
answers. Repetition is useful for testing whether later stages and judges miss
or mis-score repeated facts.

## Important Boundary

Do not validate claims in Stage 1.

Do not output:
- validation scope
- gold status
- error type
- severity
- evidence
- human note
