# Stage 2 Judge Misclassification Analysis

## Summary
- **Total verdicts**: 2,785
- **Total not_supported**: 183 (6.6%)
- **Potentially misclassified**: ~40-50 cases (to be verified by human)

---

## Category 1: OBSERVATION - Derived/Aggregated Fields (Most Suspicious) 🔴

These are claims about values that appear in tool results but may be derived or have slight mismatches in presentation.

### 1.1 Location Name Variations
**Pattern**: Claiming specific location designations that don't exactly match returned names

```
Task: I-6, Step: 7
Claim Type: observation
Reason: While the location 'QT/Stock' is returned in the step 5 tool results, 
        the designation '(main store)' does not appear in any tool result payload.

Evidence: search_stock_locations → complete_name="QT/Stock"
```

**Assessment**: ❓ POTENTIALLY MISCLASSIFIED
- If the agent said "QT/Stock (main store)" but the returned data only has "QT/Stock", 
  is that really `not_supported`? The ID and name are there; the "(main store)" label 
  might be agent inference from context.

---

### 1.2 Aggregated Numeric Values
**Pattern**: Claims about aggregated quantities where derived math is involved

```
Task: C-3, Step: 8  
Claim Type: observation
Reason: The claim references "5 available items" but the tool result shows 
        availability distributed across locations (QT: 1, HT: 4), 
        not explicitly aggregated in the payload.

Evidence: check_stock → {by_location: {QT: 1, HT: 4}}
```

**Assessment**: ❓ POTENTIALLY MISCLASSIFIED
- If `available=5` appears as an aggregated field in tool_results, it should be `supported`.
- If the agent manually sums sub-fields, guideline says "straightforward derivations are allowed"
  → might be a false `not_supported`.

---

### 1.3 Product/Bill of Materials Information
**Pattern**: Claims about product details from BOM or catalog lookups

```
Task: M-1, Step: 3
Claim Type: observation  
Claim: "Samsung Galaxy S24 (SGS24-BLK) | 1 | Smartphone"

Evidence: get_bom(bom_id=1) → lines[0] = {
  product_name: "Samsung Galaxy S24",
  sku: "SGS24-BLK",
  quantity: 1,
  category: "Smartphone"
}
```

**Assessment**: ✅ LIKELY MISCLASSIFIED (HIGH PRIORITY)
- All fields appear in the same BOM line result.
- Current guideline mentions "customer details from invoice" should be supported similarly.
- **Suggest adding this as few-shot E12 for product/BOM observations.**

---

## Category 2: ACTION_INTENTION - Possible Broad Interpretations

These are intentions that might deserve a second look on whether the agent truly showed no intent, 
or showed a similar intent that the judge judged too strictly.

### 2.1 Vague Intent vs Missing Tool
**Pattern**: Intent phrased vaguely, no obvious tool call

```
Task: PR-6, Step: 6
Reason: There are no tool calls in the same or following steps to execute 
        the stated intent of "compiling the report".

Evidence: No tool calls after step 6
```

**Assessment**: ⚠️ NEED CONTEXT
- Is "compiling report" vs "no matching tool" a genuine miss, or should the agent 
  have called a specific tool (get_report, export_report)?
- Without seeing the claim_span, hard to judge. **Needs original claim review.**

---

### 2.2 Intent with Partial Tool Match
**Pattern**: Agent calls a related but not exact tool

```
Task: D-3, Step: 6
Reason: The intent to look at what teams exist has no matching tool call; 
        the agent only fetches tickets and searches users.

Evidence: No search_teams or list_teams calls; only escalate_ticket, search_users
```

**Assessment**: ⚠️ CONTEXTUAL
- If the task only provides escalate_ticket and search_users, and no team-listing tool,
  should the verdict be `not_supported` or `needs_broader_context`?
- Might be a design-induced routing issue.

---

## Category 3: OBSERVATION - Multi-Step Composite Claims

These might be overly strict on "needs all fields in same result" rule.

```
Task: PR-2, Step: 14
Claim: "Task 17: 'Resolve launch blocker' - deadline 2026-05-01 - 
        overdue, assigned to user 14 (Nishida Web)"

Evidence Step 3: search_project_tasks → {id: 17, name: "Resolve launch blocker", 
                                         date_deadline: "2026-05-01", user_ids: [14]}
         Step 8: search_users → {id: 14, name: "Nishida Web"}
```

**Assessment**: ✅ LIKELY CORRECTLY JUDGED
- This is shown as an E7 (supported) in guideline already.
- But if there are similar multi-step observations marked `not_supported`, 
  they might be overly strict about routing.

---

## Category 4: CONSTRAINT_OR_POLICY - Task-Specific Restrictions

These look correctly judged (policy doesn't apply to current task), but worth confirming:

```
Task: H-3
Reason: Codebook rule H-05 regarding probation is explicitly 
        restricted to task H-5. Since the current task is H-3, 
        this policy does not apply.

Evidence: H-05 *(tasks: H-5)*
```

**Assessment**: ✅ CORRECTLY JUDGED
- This is proper routing. Policy H-05 has a `*(tasks: H-5)*` restriction.

---

## Top 5 Cases to Manual Review (For Human Double-Check)

These are the strongest candidates for being misclassified:

### 🔴 HIGH CONFIDENCE MISCLASSIFIED

1. **M-1 / M-5 - Product Bill of Materials Observations**
   - Claim: Multi-field product info from BOM lookup
   - Verdict: not_supported (likely wrong)
   - Action: Add E12 few-shot, extend guideline for product lookups

2. **I-6 - Location Designation Mismatch**
   - Claim: Location name with descriptive label "(main store)"
   - Verdict: not_supported
   - Action: Review whether descriptive labels are too strict

### 🟡 MEDIUM CONFIDENCE (Need Original Claim Text)

3. **PR-6 S6-C1 - Report Compilation Intent**
   - Reason: No matching tool for "compiling report"
   - Action: Check if this is ambiguous intent phrasing

4. **D-3 S6-C2 - Team Structure Intent**
   - Reason: No search_teams tool
   - Action: Check if this is design-induced (tool not available)

5. **C-3 - Aggregated Inventory Count**
   - Reason: Aggregated "5 available" from {QT: 1, HT: 4}
   - Action: Check if aggregated field exists or needs re-derivation

---

## Recommended Actions

### ✅ IMMEDIATE (High-confidence):
1. Add E12 few-shot: Product/BOM multi-field observations
2. Extend guideline boundary case for product lookups (similar to "customer details from invoice")

### 📋 FOLLOW-UP (Medium-confidence):
1. Extract actual claim_span for PR-6, D-3, C-3 cases
2. Determine if those are truly misclassified or correctly strict
3. Assess whether any need new few-shot examples for ambiguous intent phrasing

### 🔍 AUDIT:
1. Check if there are patterns in specific domains (Manufacturing, Project, etc.)
2. Confirm that few-shot expansion + guideline update reduces not_supported rate

