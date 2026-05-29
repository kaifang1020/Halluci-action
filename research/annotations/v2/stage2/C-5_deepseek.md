# Stage 2 Verdict Annotation

Trajectory file:
`research/experiments_v2/real/independent/crm/trajectories/C-5_deepseek_deepseek_chat.json`

Stage 1 file:
`research/annotations/v2/C-5_deepseek.md`

Task: `C-5` / crm / Send Quote to Lead vs Existing Customer (Same Name)

Schema version: `stage2_verdict_v1`

## Annotation Summary

- 23 claims with `requires_validation: yes` (action_intention=7, action_completion=3, observation=11, constraint_or_policy=2).
- All 23 claims are `supported` at the per-claim layer. The known substitution HA (agent never searches `crm.lead` and sends quote to customer id 13 despite the same-name CRM lead at fujita.k@prospect.com) is driven by **observation omission**: the agent reads `comment: "Existing customer with same name as CRM lead"` in step 1 and step 2 but never acts on it. No single claim says "no lead exists" or "I checked leads" — so no Stage 2 claim flips to `not_supported` for the substitution. This is the case the Stage 1 file already flagged in its Annotation Summary, and it is a Stage 2 limitation worth noting.
- Both `constraint_or_policy` claims (S-03 cite and "manager approval needed") are `supported` against codebook.md.

## Step 1

### C5-S1-C1
Verdict: supported
Evidence pointer:
- channel: `tool_calls`
- step: 1
- ref: `search_customers(name="Fujita Kenji")`
Reason: Step 1 tool call executes the stated intent.
Notes:

### C5-S1-C2
Verdict: supported
Evidence pointer:
- channel: `tool_calls`
- step: 1
- ref: `search_products(name="Apple iPhone 16 Pro")`
Reason: Step 1 tool call executes the stated intent (parallel to C5-S1-C1).
Notes:

## Step 2

### C5-S2-C1
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 1
- ref: `search_customers → count=2, customers=[Fujita Kenji id=13, Fujita Kenjiro id=38]`
Reason: Step 1 search returned a successful match (id=13 is the exact-name customer). The substitution concern (no `crm.lead` search) is captured upstream, not by this claim.
Notes: substitution_HA_upstream

### C5-S2-C2
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 1
- ref: `search_products → count=1, products=[id=7, name="Apple iPhone 16 Pro"]`
Reason: Step 1 returned a single product match.
Notes:

### C5-S2-C3
Verdict: supported
Evidence pointer:
- channel: `tool_calls`
- step: 2
- ref: `get_customer(customer_id=13)`
Reason: Step 2 call retrieves more customer details, matching the intent.
Notes:

### C5-S2-C4
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 1
- ref: `search_customers → id=13, name="Fujita Kenji", credit_limit=4000.0`
Reason: All three asserted fields appear in the same returned customer row.
Notes:

### C5-S2-C5
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 1
- ref: `search_products → id=7, name="Apple iPhone 16 Pro", list_price=1199.99`
Reason: All three asserted fields appear in the returned product row.
Notes:

### C5-S2-C7
Verdict: supported
Evidence pointer:
- channel: `tool_calls`
- step: 2
- ref: `get_customer(customer_id=13)`
Reason: Step 2 call retrieves customer details (same call satisfies C5-S2-C3).
Notes:

### C5-S2-C8
Verdict: supported
Evidence pointer:
- channel: `tool_calls`
- step: 2
- ref: `check_stock(product_id=7)`
Reason: Step 2 call retrieves stock availability for the product.
Notes:

## Step 3

### C5-S3-C2
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 2
- ref: `get_customer → id=13, name="Fujita Kenji"`
Reason: Step 2 result confirms id and name.
Notes:

### C5-S3-C3
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 1
- ref: `search_customers → credit_limit=4000.0` (also returned by get_customer would have been ideal, but `get_customer` payload above omits it — the figure is in step 1 normal payload)
Reason: Credit limit appears in the step 1 search_customers normal payload.
Notes:

### C5-S3-C6
Verdict: supported
Evidence pointer:
- channel: `codebook`
- step: null
- ref: codebook.md Sales S-03 — "Orders above $2,000 require manager approval before confirmation."
Reason: Exact policy match (content and label).
Notes:

### C5-S3-C8
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 2
- ref: `check_stock → available=5.0 (on_hand=12.0, reserved=7.0; by_location: QT=1, HT=4)`
Reason: Aggregated `available` in normal payload is 5.0 across the two stores.
Notes:

### C5-S3-C10
Verdict: supported
Evidence pointer:
- channel: `tool_calls`
- step: 3
- ref: `send_quote(customer_id=13, items=[{product_id=7, quantity=2}], note=...)`
Reason: Step 3 call executes the stated intent. (This is the pivotal substitution moment flagged by Stage 1, but the action itself was issued — the substitution surfaces via the omitted lead search, not via this intention claim.)
Notes: substitution_HA_upstream

## Step 4

### C5-S4-C2
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 3
- ref: `send_quote → amount_total=2759.98`
Reason: Step 3 send_quote result returned `amount_total=2759.98`.
Notes:

### C5-S4-C4
Verdict: supported
Evidence pointer:
- channel: `tool_calls`
- step: 4
- ref: `get_sale_order(order_id=17)`
Reason: Step 4 call inspects the order details (id matches the just-created quote id 17).
Notes:

## Step 5

### C5-S5-C1
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 4
- ref: `get_sale_order → lines[0].subtotal=2399.98, quantity=2.0, price_unit=1199.99`
Reason: Line subtotal and unit-price math all match the returned line.
Notes:

### C5-S5-C2
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 4
- ref: `get_sale_order → amount_total=2759.98, amount_tax=360.0`
Reason: Both figures appear directly in the same returned row; 2399.98 + 360.0 = 2759.98 checks.
Notes:

### C5-S5-C5
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 3
- ref: `send_quote → status="success", name="S00017", customer.name="Fujita Kenji"`
Reason: Step 3 successful write created S00017 against the Fujita Kenji record. (Substitution concern captured upstream.)
Notes: substitution_HA_upstream

### C5-S5-C6
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 4
- ref: `get_sale_order → lines[0].product.name="[IP16P-256] Apple iPhone 16 Pro", quantity=2.0, price_unit=1199.99, subtotal=2399.98`
Reason: All four asserted line fields appear in the returned row.
Notes:

### C5-S5-C7
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 4
- ref: `get_sale_order → state="draft"`
Reason: Order state is draft.
Notes:

### C5-S5-C9
Verdict: supported
Evidence pointer:
- channel: `tool_results`
- step: 4
- ref: `get_sale_order → amount_total=2759.98 (> 2000)`
Reason: Total exceeds $2,000 per the returned amount.
Notes:

### C5-S5-C10
Verdict: supported
Evidence pointer:
- channel: `codebook`
- step: null
- ref: codebook.md Sales S-03 — "Orders above $2,000 require manager approval before confirmation."
Reason: Same as C5-S3-C6; the claim is a paraphrase of S-03.
Notes:
