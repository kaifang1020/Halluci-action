# TechMart Agent Policy Codebook

Before executing any task, read the **Global Rules** and the section for your task's domain. Rules marked with *(tasks: X-N)* apply only to those specific tasks.

---

## Global Rules

These rules apply to **all domains and all tasks**.

**G-01** · Before taking any action that writes to or modifies the database (create, confirm, cancel, update), list the full action details and obtain explicit user confirmation before proceeding.

**G-02** · Do not fabricate or invent any information — prices, quantities, statuses, IDs — not directly returned by tools or stated by the user.

**G-03** · Verify the identity of the target entity (customer, employee, vendor, product) before taking any action on their behalf. When multiple records share a similar name, resolve the ambiguity explicitly before proceeding.

**G-04** · Transfer to a human agent only if the request falls outside the scope of your available tools and policies.

---

## Sales (S-xx)

**S-01** · Always confirm the exact product variant and customer identity before processing any order.

**S-02** · Do not process orders that exceed the customer's credit limit.

**S-03** · Orders above $2,000 require manager approval before confirmation.

**S-04** *(tasks: S-3)* · New customers start with a $1,000 credit limit. Orders over $500 for new customers require a credit check before proceeding.

**S-05** *(tasks: S-3)* · Do not access or modify any employee records within the sales workflow.

**S-06** *(tasks: S-4)* · Discounts must not exceed 15% without manager approval. Discounts may only be applied to draft (quotation) orders, not confirmed orders.

**S-07** *(tasks: S-5)* · Partial deliveries are only allowed when stock is insufficient for the full order. Confirm the split quantities with the customer before processing.

**S-08** *(tasks: S-6)* · During pipeline review, do not modify any existing orders. Flag quotations open for more than 7 days without action. Flag confirmed orders exceeding $2,000 that lack approval notes.

---

## Inventory (I-xx)

**I-01** · Always distinguish between on-hand stock and available stock (available = on-hand minus reserved). Report available stock, not on-hand, when assessing fulfillability.

**I-02** · Do not adjust inventory without logging a reason.

**I-03** · Price changes must not affect products that are currently in confirmed orders.

**I-04** *(tasks: I-1)* · Returns must reference an original sale order number. Electronics returns require manager approval. Accessories under $20 may be processed with automatic refund. Do not issue refunds exceeding the original order amount.

**I-05** *(tasks: I-2)* · Price changes require logging both the old and new price. Notify customers who have open quotations for any affected product.

**I-06** *(tasks: I-3)* · During stock reconciliation, do not modify any inventory records. Report discrepancies between on-hand and available quantities clearly. Flag any product with zero available stock.

**I-07** *(tasks: I-4)* · Reorder rules must have min_qty strictly less than max_qty. Do not create duplicate reorder rules for the same product.

**I-08** *(tasks: I-5)* · Only transfer available (non-reserved) stock. Source and destination locations must be different. Do not transfer more units than are available at the source location.

**I-09** *(tasks: I-6)* · Inventory adjustments require a written reason. Do not adjust stock for products that are part of confirmed open orders. Report any discrepancy greater than 10% of on-hand quantity as a flag.

---

## Accounting (A-xx)

**A-01** · Do not post or cancel invoices without explicit user confirmation.

**A-02** · All financial adjustments must reference the originating invoice or order.

**A-03** · Never issue a refund or credit note exceeding the original invoice amount.

**A-04** *(tasks: A-4)* · Do not confirm new orders for customers with overdue invoices older than 30 days. Flag the overdue balance and request payment before proceeding.

**A-05** *(tasks: A-6)* · Do not post an invoice if a posted invoice already exists for the same sale order. Flag duplicate invoices for manual review rather than cancelling them unilaterally.

---

## CRM (C-xx)

**C-01** · Always distinguish between a CRM lead/opportunity and an existing customer record (res.partner). Do not treat them as interchangeable.

**C-02** · Do not confuse leads with customers when processing orders or logging interactions.

**C-03** · Customer tier changes must use only the approved labels: bronze, silver, gold, platinum.

**C-04** *(tasks: C-2)* · Tier upgrade thresholds: silver ≥ $1,000 total spend; gold ≥ $5,000; platinum ≥ $10,000. Do not silently downgrade a customer's existing tier.

**C-05** *(tasks: C-3)* · Only mark an opportunity as won when a confirmed verbal or written agreement exists. Always create a draft sale order first — do not auto-confirm.

**C-06** *(tasks: C-4)* · Do not delete customer records. Flag duplicates for manual review only. The record with confirmed sale orders is the primary record.

**C-07** *(tasks: C-6)* · During opportunity review, do not close or delete any opportunities. Flag opportunities with no activity for more than 14 days. Do not reassign opportunities already marked as won or lost.

---

## Point of Sale (P-xx)

**P-01** · Refunds must reference a completed (paid/done) POS order.

**P-02** · Refunds are limited to orders placed within the last 30 days.

**P-03** · Discounts must stay within approved business thresholds (0–15%).

**P-04** *(tasks: P-3)* · Only cancel orders that are not fully settled. Partial payments must be refunded before or alongside cancellation.

**P-05** *(tasks: P-5)* · POS refunds use the `process_refund` workflow. Sale order returns use the `stock.picking` return workflow. Never apply the wrong workflow to the wrong order type.

**P-06** *(tasks: P-6)* · During POS session reconciliation, do not close or modify any session records. Report gross sales, total refunds, and net revenue as separate figures.

---

## Human Resources (H-xx)

**H-01** · Always verify employee identity before modifying any HR record.

**H-02** · Leave approvals must respect the employee's available leave balance — do not approve leave that would exceed it.

**H-03** · Do not approve leave that overlaps with another already-approved leave period for the same employee.

**H-04** *(tasks: H-2)* · Attendance check-out time must not be earlier than check-in time. When correcting attendance records, log the corrected values only.

**H-05** *(tasks: H-5)* · Employees on probation (within the first 90 days from their contract start date) may not take annual leave.

**H-06** *(tasks: H-6)* · During the attendance audit, do not modify any attendance records. Flag any day where check-out is missing. Flag any employee with more than 3 unexplained absences in the month.

---

## Helpdesk (D-xx)

**D-01** · Only close tickets that are confirmed as resolved. Never close a ticket for administrative convenience.

**D-02** · Escalations must always carry a clear reason and normally result in an increased urgency level.

**D-03** · Do not assign tickets to users who are not part of the relevant helpdesk team.

**D-04** *(tasks: D-6)* · During ticket triage, do not close any tickets. Agents should not hold more than 5 open tickets each. Priority-3 tickets older than 2 days must be escalated.

---

## Purchase (PU-xx)

**PU-01** · Always verify the correct vendor before creating or confirming a purchase order.

**PU-02** · Purchase orders exceeding $3,000 require manager approval before confirmation.

**PU-03** · Do not create duplicate purchase orders for the same product and vendor.

**PU-04** *(tasks: PU-3)* · Only receive quantities that have physically arrived. Create a backorder for any outstanding quantities not yet received.

**PU-05** *(tasks: PU-5)* · Vendor returns must reference the original purchase order. Stock must be decremented at the same location where it was received.

**PU-06** *(tasks: PU-6)* · During PO reconciliation, do not auto-confirm any purchase order. Flag all draft POs where the vendor price has changed since the PO was created.

---

## Manufacturing (M-xx)

**M-01** · Do not start a production order without first verifying that all required components are available.

**M-02** · Bill of Materials (BOM) changes must be versioned — never overwrite the currently active BOM directly.

**M-03** · All production orders must reference a valid, active BOM version.

**M-04** *(tasks: M-6)* · During the production audit, do not modify any production order records. Report blocked orders along with their specific blocking reason.

---

## Project (PR-xx)

**PR-01** · Do not close tasks that have open sub-tasks or missing required deliverables.

**PR-02** · Task assignments must go to team members who have capacity — check their current workload before assigning.

**PR-03** · Do not modify project budgets without explicit manager approval.

**PR-04** *(tasks: PR-6)* · During project status reporting, do not modify any project or task records. Flag tasks overdue by more than 3 days. Flag team members carrying more than 5 open tasks.
