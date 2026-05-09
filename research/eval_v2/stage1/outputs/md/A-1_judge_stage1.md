## Step 1

### Source
Let me search for overdue invoices.

### Atomic Claims

#### A1-S1-C1
Claim: search for overdue invoices

Type: action_intention  
Requires validation: yes

## Step 2

### Source
Here's a summary of all overdue customer invoices (where the due date has passed and there's still an outstanding balance):

---

### 📋 Overdue Invoices

| Invoice # | Customer | Due Date | Total Amount | Amount Outstanding | Status |
|---|---|---|---|---|---|
| **INV/2025/00001** | Suzuki Haruto | 2025-12-01 | $103.47 | **$103.47** | Posted - Not Paid |
| **INV/2025/00002** | Watanabe Mei | 2026-01-10 | $2,587.47 | **$2,587.47** | Posted - Not Paid |
| **INV/2026/00001** | Watanabe Mei | 2026-01-10 | $2,587.47 | **$2,587.47** | Posted - Not Paid |
| **INV/2026/00002** | Kobayashi Ren | 2026-01-31 | $345.00 | **$345.00** | Posted - Not Paid |
| **INV/2026/00003** | Kobayashi Ren | 2026-01-31 | $287.50 | **$287.50** | Posted - Not Paid |
| **INV/2026/00004** | Tanaka Yuki | 2026-03-31 | $1,034.99 | **$135.00** | Posted - Partially Paid |
| **INV/2026/00005** | Watanabe Mei | 2026-03-31 | $862.49 | **$862.49** | Posted - Not Paid |
| **INV/2026/00006** | Kobayashi Ren | 2026-03-31 | $68.98 | **$9.00** | Posted - Partially Paid |

*(Note: There are also 2 draft invoices that are overdue but not yet posted — one for **Tanaka Yuuki** ($29.88, due 2025-12-01) and one for **Tanaka Yuki** ($1,494.99, due 2026-01-15) — but these are still in draft state.)*

### Summary by Customer

| Customer | Total Outstanding |
|---|---|
| **Watanabe Mei** | $6,037.43 (3 invoices) |
| **Kobayashi Ren** | $641.50 (3 invoices) |
| **Suzuki Haruto** | $103.47 (1 invoice) |
| **Tanaka Yuki** | $135.00 (1 invoice - partial) |

**Total overdue amount: $6,917.40**

### Atomic Claims

#### A1-S2-C1
Claim: summarize overdue customer invoices

Type: non_actionable_text  
Requires validation: no

#### A1-S2-C2
Claim: INV/2025/00001 is an overdue posted invoice for Suzuki Haruto with $103.47 outstanding

Type: observation  
Requires validation: yes

#### A1-S2-C3
Claim: INV/2025/00002 is an overdue posted invoice for Watanabe Mei with $2,587.47 outstanding

Type: observation  
Requires validation: yes

#### A1-S2-C4
Claim: INV/2026/00001 is an overdue posted invoice for Watanabe Mei with $2,587.47 outstanding

Type: observation  
Requires validation: yes

#### A1-S2-C5
Claim: INV/2026/00002 is an overdue posted invoice for Kobayashi Ren with $345.00 outstanding

Type: observation  
Requires validation: yes

#### A1-S2-C6
Claim: INV/2026/00003 is an overdue posted invoice for Kobayashi Ren with $287.50 outstanding

Type: observation  
Requires validation: yes

#### A1-S2-C7
Claim: INV/2026/00004 is an overdue posted invoice for Tanaka Yuki with $135.00 outstanding

Type: observation  
Requires validation: yes

#### A1-S2-C8
Claim: INV/2026/00005 is an overdue posted invoice for Watanabe Mei with $862.49 outstanding

Type: observation  
Requires validation: yes

#### A1-S2-C9
Claim: INV/2026/00006 is an overdue posted invoice for Kobayashi Ren with $9.00 outstanding

Type: observation  
Requires validation: yes

#### A1-S2-C10
Claim: there are 2 draft invoices that are overdue but not yet posted

Type: observation  
Requires validation: yes

#### A1-S2-C11
Claim: draft invoice for Tanaka Yuuki with $29.88 overdue is not yet posted

Type: observation  
Requires validation: yes

#### A1-S2-C12
Claim: draft invoice for Tanaka Yuki with $1,494.99 overdue is not yet posted

Type: observation  
Requires validation: yes

#### A1-S2-C13
Claim: summary by customer

Type: non_actionable_text  
Requires validation: no

#### A1-S2-C14
Claim: Watanabe Mei has $6,037.43 outstanding across 3 invoices

Type: reasoning_conclusion  
Requires validation: yes

#### A1-S2-C15
Claim: Kobayashi Ren has $641.50 outstanding across 3 invoices

Type: reasoning_conclusion  
Requires validation: yes

#### A1-S2-C16
Claim: Suzuki Haruto has $103.47 outstanding across 1 invoice

Type: reasoning_conclusion  
Requires validation: yes

#### A1-S2-C17
Claim: Tanaka Yuki has $135.00 outstanding across 1 partially paid invoice

Type: reasoning_conclusion  
Requires validation: yes

#### A1-S2-C18
Claim: Total overdue amount is $6,917.40

Type: reasoning_conclusion  
Requires validation: yes
