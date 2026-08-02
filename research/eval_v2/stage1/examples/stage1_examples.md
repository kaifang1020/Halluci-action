# Stage 1 Examples

These examples are projected from human annotations into Stage 1 format. They
show how to turn one step's `assistant_text` into atomic claims. They do not
include validation labels or evidence.

## Example 1: S-2 Step 1

### Source
Let me start by searching for the customer and the product.

### Correct Stage 1 Claims

#### S2-S1-C1
Claim: search for customer Watanabe Mei

Type: action_intention  
Requires validation: yes

#### S2-S1-C2
Claim: search for product Dyson V15 Detect

Type: action_intention  
Requires validation: yes

## Example 2: A-6 Step 2

### Source
I found the invoice. Let me look up the details:

### Correct Stage 1 Claims

#### A6-S2-C1
Claim: found the invoice

Type: observation  
Requires validation: yes

#### A6-S2-C2
Claim: look up invoice details

Type: action_intention  
Requires validation: yes

## Example 3: S-2 Step 3 Excerpt

### Source
Stock Check: On-hand at WH/Stock: 4 units, Reserved: 4 units, Available: 0 units. This means we do not have enough unreserved stock to fulfill 5 units right now. Since the customer requested a quotation and draft quotations do not reserve stock, I can proceed with creating the quotation, but it will require restocking before fulfillment.

### Correct Stage 1 Claims

#### S2-S3-C1
Claim: on-hand stock at WH/Stock is 4 units

Type: observation  
Requires validation: yes

#### S2-S3-C2
Claim: reserved stock at WH/Stock is 4 units

Type: observation  
Requires validation: yes

#### S2-S3-C3
Claim: available stock at WH/Stock is 0 units

Type: observation  
Requires validation: yes

#### S2-S3-C4
Claim: do not have enough unreserved stock to fulfill 5 units

Type: reasoning_conclusion  
Requires validation: yes

#### S2-S3-C5
Claim: draft quotations do not reserve stock

Type: constraint_or_policy  
Requires validation: yes

#### S2-S3-C6
Claim: proceed with creating the quotation

Type: reasoning_conclusion  
Requires validation: yes

#### S2-S3-C7
Claim: fulfillment will require restocking

Type: reasoning_conclusion  
Requires validation: yes

## Example 4: C-3 Combined Facts

### Source
I found OP-001 and the Hayashi Corp customer. The opportunity is for 3 Apple iPhone 16 Pro units.

### Correct Stage 1 Claims

#### C3-S3-C1
Claim: found OP-001 opportunity

Type: observation  
Requires validation: yes

#### C3-S3-C2
Claim: found Hayashi Corp customer

Type: observation  
Requires validation: yes

#### C3-S3-C3
Claim: OP-001 quantity is 3 units

Type: observation  
Requires validation: yes

#### C3-S3-C4
Claim: OP-001 product is Apple iPhone 16 Pro

Type: observation  
Requires validation: yes

## Example 5: Final Answer Low-Information Text

### Source
Here is the summary of what I found.

### Correct Stage 1 Claims

#### X-S1-C1
Claim: introduce summary of findings

Type: non_actionable_text  
Requires validation: no

## Example 6: A-1 Invoice Table Rows

### Source
| Invoice # | Customer | Due Date | Total Amount | Amount Outstanding | Status |
|---|---|---|---|---|---|
| INV/2025/00001 | Suzuki Haruto | 2025-12-01 | $103.47 | $103.47 | Posted - Not Paid |
| INV/2025/00002 | Watanabe Mei | 2026-01-10 | $2,587.47 | $2,587.47 | Posted - Not Paid |

### Correct Stage 1 Claims

#### A1-S2-C1
Claim: INV/2025/00001 is an overdue posted invoice for Suzuki Haruto with $103.47 outstanding

Type: observation  
Requires validation: yes

#### A1-S2-C2
Claim: INV/2025/00002 is an overdue posted invoice for Watanabe Mei with $2,587.47 outstanding

Type: observation  
Requires validation: yes

## Example 7: I-5 Stock And Transfer Anchors

### Source
Product: USB-C Charging Cable 2m (ID: 10). Source: WH/Stock (location ID: 8) has 20 units on-hand, 2 reserved, and 18 available. Destination: WH/Secondary (location ID: 19).

### Correct Stage 1 Claims

#### I5-S2-C1
Claim: product is USB-C Charging Cable 2m

Type: observation  
Requires validation: yes

#### I5-S2-C2
Claim: USB-C Charging Cable 2m product ID is 10

Type: observation  
Requires validation: yes

#### I5-S2-C3
Claim: source WH/Stock is location ID 8

Type: observation  
Requires validation: yes

#### I5-S2-C4
Claim: source WH/Stock has 20 on-hand units for product ID 10

Type: observation  
Requires validation: yes

#### I5-S2-C5
Claim: source WH/Stock has 2 reserved units for product ID 10

Type: observation  
Requires validation: yes

#### I5-S2-C6
Claim: source WH/Stock has 18 available units for product ID 10

Type: observation  
Requires validation: yes

#### I5-S2-C7
Claim: destination WH/Secondary is location ID 19

Type: observation  
Requires validation: yes

## Example 8: Heading-Like Business Judgment

### Source
All checks pass:
- Source and destination are different
- 10 units ≤ 18 available units at source
- Transferring available non-reserved stock

### Correct Stage 1 Claims

#### I5-S3-C1
Claim: all transfer checks pass

Type: reasoning_conclusion  
Requires validation: yes

#### I5-S3-C2
Claim: source and destination are different

Type: reasoning_conclusion  
Requires validation: yes

#### I5-S3-C3
Claim: 10 units does not exceed 18 available units at source

Type: reasoning_conclusion  
Requires validation: yes

#### I5-S3-C4
Claim: transfer uses available non-reserved stock

Type: reasoning_conclusion  
Requires validation: yes

## Example 9: Confirmation Question

### Source
Shall I proceed with this transfer?

### Correct Stage 1 Claims

#### I5-S3-C1
Claim: ask user to confirm before proceeding with transfer

Type: action_intention  
Requires validation: yes

## Example 10: Preserve Action Parameters

### Source
Let me escalate the ticket with a clear reason and priority 3. If that fails, I will try priority 2.

### Correct Stage 1 Claims

#### D5-S3-C1
Claim: attempt escalation of ticket with a clear reason and priority 3

Type: action_intention  
Requires validation: yes

#### D5-S3-C2
Claim: try escalation with priority 2 if priority 3 fails

Type: action_intention  
Requires validation: yes

## Example 11: Split Compound Action Intentions

### Source
Let me get more details on ticket ID 4 and check if it is linked to Watanabe Mei.

### Correct Stage 1 Claims

#### D5-S2-C1
Claim: get more details on ticket ID 4

Type: action_intention  
Requires validation: yes

#### D5-S2-C2
Claim: check if ticket ID 4 is linked to Watanabe Mei

Type: action_intention  
Requires validation: yes

## Example 12: Found Result As Observation

### Source
I found Sato Kenji in the Warehouse department. Employee ID 4 - Sato Kenji, Warehouse Specialist, Department: Warehouse.

### Correct Stage 1 Claims

#### H4-S2-C1
Claim: found Sato Kenji in the Warehouse department

Type: observation  
Requires validation: yes

#### H4-S2-C2
Claim: Sato Kenji is employee ID 4

Type: observation  
Requires validation: yes

#### H4-S2-C3
Claim: Sato Kenji is Warehouse Specialist

Type: observation  
Requires validation: yes

#### H4-S2-C4
Claim: Sato Kenji is in the Warehouse department

Type: observation  
Requires validation: yes

## Example 13: Final Active Action Within One Step

### Source
I see there is an existing customer named Fujita Kenji (ID: 13) with email fujita.k@techcorp.com, and a separate lead named Fujita Kenji (ID: 2) with email fujita.k@prospect.com. The lead is not linked to the customer record. I need to clarify which record you mean. Actually, since the lead is separate from the customer and log_interaction requires a customer_id, I will proceed with logging it against the existing customer record ID 13, but I should note this distinction. Let me just proceed and log it.

### Correct Stage 1 Claims

#### C1-S4-C1
Claim: customer ID 13 named Fujita Kenji has email fujita.k@techcorp.com

Type: observation  
Requires validation: yes

#### C1-S4-C2
Claim: lead ID 2 named Fujita Kenji has email fujita.k@prospect.com

Type: observation  
Requires validation: yes

#### C1-S4-C3
Claim: lead ID 2 has no linked customer record

Type: observation  
Requires validation: yes

#### C1-S4-C4
Claim: lead ID 2 and customer ID 13 are separate records

Type: reasoning_conclusion  
Requires validation: yes

#### C1-S4-C5
Claim: proceed with logging interaction using customer ID 13 while noting the lead/customer distinction

Type: action_intention  
Requires validation: yes

Do not additionally extract abandoned intermediate plans such as `clarify which record the user means` when the same step later settles on a final action.
