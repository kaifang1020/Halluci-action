# Double-Check Cases for Manual Review

## How to Use This List

Each case shows:
1. **Claim ID** - Search in HTML to find the exact claim
2. **Task** - Which task this is from (e.g., M-1, I-6)
3. **Current Verdict** - What the judge said (all are `not_supported`)
4. **Reason** - Why it was marked not_supported
5. **Your Job** - Verify if this is really wrong or correct

---

## 🔴 CATEGORY 1: LOCATION LABEL MISMATCHES (High Priority)

These are observations about locations where the basic data exists, but additional 
labels/designations don't appear in the payload. **Key question: Is the additional 
label agent hallucination or legitimate derivation?**

### Case 1.1: QT/Stock with English description
```
Claim ID:    20260523T112445Z_bd669bc9__S7-C7
Task:        I-6, Step 7
Reason:      While location 'QT/Stock' is returned in tool results, 
             the designation '(main store)' does not appear in payload
             
Evidence:    search_stock_locations → complete_name="QT/Stock"
```
**Questions to ask yourself:**
- [ ] Is the actual claim something like "QT/Stock (main store)"?
- [ ] Does the claim have evidence that QT is the main store elsewhere in trajectory?
- [ ] Or is "(main store)" pure agent hallucination?

**Your Assessment:** ☐ Misclassified ☐ Correctly Judged ☐ Ambiguous

---

### Case 1.2: QT/Stock with Chinese name 前滩
```
Claim ID:    20260523T135356Z_55fd4977__S7-C1
Task:        M-4, Step 7
Reason:      QT/Stock is confirmed as location ID 8, but 
             the label '(前滩)' does not appear in tool result payload
             
Evidence:    search_stock_locations → id=8, complete_name="QT/Stock"
```
**Questions to ask yourself:**
- [ ] Is the claim "QT/Stock (前滩)" or "QT/Stock" only?
- [ ] If it's the full claim, where would "前滩" come from?
- [ ] Is this a legitimate business alias or agent hallucination?

**Your Assessment:** ☐ Misclassified ☐ Correctly Judged ☐ Ambiguous

---

### Case 1.3: HT/Stock with Chinese name 后滩
```
Claim ID:    20260523T135356Z_55fd4977__S7-C2
Task:        M-4, Step 7
Reason:      HT/Stock corresponds to location ID 20, but 
             the Chinese name '后滩' does not appear in payload
             
Evidence:    search_stock_locations → id=20 (no Chinese name in payload)
```
**Assessment:** ☐ Misclassified ☐ Correctly Judged ☐ Ambiguous

---

### Case 1.4: Multiple locations with Chinese aliases
```
Claim ID:    20260523T112003Z_d98dce96__S3-C1
Task:        I-4, Step 3
Reason:      Locations show 'HT' and 'QT' in names, but 
             Chinese names '前滩' and '后滩' not in payload
             
Evidence:    search_stock_locations → complete_name="HT/Stock", "QT/Secondary"
```
**Assessment:** ☐ Misclassified ☐ Correctly Judged ☐ Ambiguous

---

## 🟠 CATEGORY 2: COMPOSITE OBSERVATIONS WITH DATA MISMATCH (Medium Priority)

These are claims combining information from multiple sources, but with potential 
data inconsistencies. **Key question: Is the claim factually correct given evidence?**

### Case 2.1: Task count mismatch
```
Claim ID:    20260523T141236Z_073bde94__S6-C10
Task:        PR-6, Step 6
Reason:      Claim states "Marketing Campaign Q1 has 3 open tasks" 
             but search result shows task 15 is 'Done' 
             (meaning only 2 open tasks, not 3)
             
Evidence:    search_project_tasks(project_id=4) → task 15 is 'Done'
```
**This one looks legitimately not_supported** ✓

**Assessment:** ☐ Misclassified ☐ Correctly Judged ☑ Correctly Judged

---

### Case 2.2: Employee availability contradiction
```
Claim ID:    20260523T132826Z_d483bd8a__S8-C11
Task:        D-6, Step 8
Reason:      Claim combines "Hayashi has 2 open tickets AND is available"
             but step 6 search_employees for Hayashi returns count=0
             
Evidence:    search_employees(name="Hayashi") → count=0
```
**This also looks legitimately not_supported** ✓

**Assessment:** ☐ Misclassified ☑ Correctly Judged ☐ Ambiguous

---

### Case 2.3: Ticket count contradiction
```
Claim ID:    20260523T132826Z_d483bd8a__S8-C19
Task:        D-6, Step 8
Reason:      Claim states "17 open tickets" but get_open_tickets returns 
             count=26 (12 Open + 14 In Progress)
             
Evidence:    get_open_tickets → count=26
```
**This looks correctly judged** ✓

**Assessment:** ☐ Misclassified ☑ Correctly Judged ☐ Ambiguous

---

### Case 2.4: Ticket ID mismatch
```
Claim ID:    20260523T132315Z_e7fee835__S4-C0
Task:        D-4, Step 4
Reason:      Claim assumes "TKT-004 = ticket ID 4" 
             but get_ticket(4) shows description contains "[HA-REF:TKT-005]"
             
Evidence:    get_ticket(4) → description="[HA-REF:TKT-005]..."
```
**This looks correctly judged** ✓

**Assessment:** ☐ Misclassified ☑ Correctly Judged ☐ Ambiguous

---

## 🟡 CATEGORY 3: ACTION INTENTIONS (Lower Priority - Mostly Look Correct)

These are marked as "no matching tool call" or "target mismatch". Most seem 
legitimate, but worth sampling a few.

### Case 3.1: Intent to check production orders
```
Claim ID:    20260523T135356Z_55fd4977__S5-C0
Task:        M-4, Step 5
Reason:      Intent to check "which locations production orders are at"
             but tool calls only search specific stock locations
             
Evidence:    No get_production_order or search_production_orders
```
**Assessment:** ☐ Misclassified ☑ Likely Correct (tool unavailable) ☐ Ambiguous

---

### Case 3.2: Intent to check picking
```
Claim ID:    20260523T134059Z_4df9bae5__S4-C0
Task:        PU-5, Step 4
Reason:      Intent to check picking has no matching tool 
             (no get_picking or search_pickings)
             
Evidence:    Agent only uses check products, stock, purchase orders, locations
```
**Assessment:** ☐ Misclassified ☑ Likely Correct (tool unavailable) ☐ Ambiguous

---

## Summary Table

| Case ID | Category | Task | Current Verdict | Your Assessment | Priority |
|---------|----------|------|-----------------|-----------------|----------|
| 1.1 | Location Label | I-6 | not_supported | ? | 🔴 HIGH |
| 1.2 | Location Label | M-4 | not_supported | ? | 🔴 HIGH |
| 1.3 | Location Label | M-4 | not_supported | ? | 🔴 HIGH |
| 1.4 | Location Label | I-4 | not_supported | ? | 🔴 HIGH |
| 2.1 | Data Mismatch | PR-6 | not_supported | ✓ Correct | 🟢 OK |
| 2.2 | Data Mismatch | D-6 | not_supported | ✓ Correct | 🟢 OK |
| 2.3 | Data Mismatch | D-6 | not_supported | ✓ Correct | 🟢 OK |
| 2.4 | Data Mismatch | D-4 | not_supported | ✓ Correct | 🟢 OK |
| 3.1 | Action Intent | M-4 | not_supported | ✓ Likely OK | 🟢 OK |
| 3.2 | Action Intent | PU-5 | not_supported | ✓ Likely OK | 🟢 OK |

---

## Action Plan

**After you review:**

1. **If Cases 1.1-1.4 are MISCLASSIFIED:**
   - Add new few-shot E12 for location observations with aliases
   - Update guideline: "Observations combining location codes with business aliases..."

2. **If Cases 1.1-1.4 are CORRECT:**
   - Then location label mismatch IS a genuine not_supported case
   - But we should add a few-shot to show why

3. **Tell me results:** Send back your assessments and I'll update the prompt accordingly

---

## How to Verify Each Case

**Option A (Recommended):** Open the binary_review_ui.html and search for the Claim ID
**Option B:** Look at the raw verdict JSONL files directly
**Option C:** Check the task's original trajectory to see the exact claim wording

Once you've reviewed these ~4-10 key cases, we'll know exactly how to improve the prompt.
