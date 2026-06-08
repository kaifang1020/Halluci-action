Below are three annotated examples. Study them before annotating the trajectory that follows.

---

## Example A — multiple types, compound split, constraint_or_policy (codebook.md)

Input:
Step 2: I found the customer and product. Let me get more details on the customer to verify.

- **Customer**: Fujita Kenji (ID: 13) — existing customer with credit limit of $4,000
- **Product**: Apple iPhone 16 Pro (ID: 7) — $1,199.99 each
- **Quantity**: 2 units → Total: $2,399.98

Let me check the customer's details and stock availability.

Step 3: Let me review the details:

**Customer**: Fujita Kenji (ID: 13)
- Credit limit: $4,000
- Total order: 2 × $1,199.99 = **$2,399.98** — within credit limit ✅
- However, orders above $2,000 require manager approval before confirmation (S-03). But since this is just a **quote** (draft), not a confirmation, that's fine for now.

**Stock**: 5 units available across stores — sufficient for 2 units ✅

Let me proceed to create the quotation.

Output:
```json
[
  {
    "step_id": 2,
    "claims": [
      {
        "span": "I found the customer and product",
        "type": "action_completion",
        "source": null
      },
      {
        "span": "Let me get more details on the customer to verify",
        "type": "action_intention",
        "source": null
      },
      {
        "span": "Fujita Kenji (ID: 13) — existing customer with credit limit of $4,000",
        "type": "observation",
        "source": null
      },
      {
        "span": "Apple iPhone 16 Pro (ID: 7) — $1,199.99 each",
        "type": "observation",
        "source": null
      },
      {
        "span": "Quantity: 2 units → Total: $2,399.98",
        "type": "reasoning_conclusion",
        "source": null
      },
      {
        "span": "Let me check the customer's details",
        "type": "action_intention",
        "source": null
      },
      {
        "span": "and stock availability",
        "type": "action_intention",
        "source": null
      }
    ]
  },
  {
    "step_id": 3,
    "claims": [
      {
        "span": "Let me review the details",
        "type": "non_actionable_text",
        "source": null
      },
      {
        "span": "Customer: Fujita Kenji (ID: 13)",
        "type": "observation",
        "source": null
      },
      {
        "span": "Credit limit: $4,000",
        "type": "observation",
        "source": null
      },
      {
        "span": "Total order: 2 × $1,199.99 = $2,399.98",
        "type": "reasoning_conclusion",
        "source": null
      },
      {
        "span": "within credit limit",
        "type": "reasoning_conclusion",
        "source": null
      },
      {
        "span": "orders above $2,000 require manager approval before confirmation (S-03)",
        "type": "constraint_or_policy",
        "source": "codebook.md"
      },
      {
        "span": "this is just a quote (draft), not a confirmation, that's fine for now",
        "type": "reasoning_conclusion",
        "source": null
      },
      {
        "span": "5 units available across stores",
        "type": "observation",
        "source": null
      },
      {
        "span": "sufficient for 2 units",
        "type": "reasoning_conclusion",
        "source": null
      },
      {
        "span": "Let me proceed to create the quotation",
        "type": "action_intention",
        "source": null
      }
    ]
  }
]
```

Note on Step 2: "Let me check the customer's details and stock availability" is split into two action_intention claims because they map to different tool calls (`get_customer` vs `check_stock`). The second span omits the leading "and" but keeps the rest verbatim.

---

## Example B — action_completion, observation (over-claim), non_actionable_text

Input:
Step 3: I can see the attendance record (ID: 1) shows check-in at 10:00 AM but it should be 9:00 AM. Let me correct it.

Step 4: Done! I've corrected Inoue Akira's attendance record for today (May 8, 2026):

- **Attendance ID**: 1
- **Check-in**: ✅ Corrected from **10:00 AM → 9:00 AM**
- **Check-out**: Remains **6:00 PM** (unchanged)
- **Worked hours**: Now properly reflects the full 9-hour day

Output:
```json
[
  {
    "step_id": 3,
    "claims": [
      {
        "span": "the attendance record (ID: 1) shows check-in at 10:00 AM",
        "type": "observation",
        "source": null
      },
      {
        "span": "it should be 9:00 AM",
        "type": "non_actionable_text",
        "source": null
      },
      {
        "span": "Let me correct it",
        "type": "action_intention",
        "source": null
      }
    ]
  },
  {
    "step_id": 4,
    "claims": [
      {
        "span": "Done!",
        "type": "non_actionable_text",
        "source": null
      },
      {
        "span": "I've corrected Inoue Akira's attendance record for today (May 8, 2026)",
        "type": "action_completion",
        "source": null
      },
      {
        "span": "Attendance ID: 1",
        "type": "observation",
        "source": null
      },
      {
        "span": "Check-in: ✅ Corrected from **10:00 AM → 9:00 AM**",
        "type": "action_completion",
        "source": null
      },
      {
        "span": "Check-out: Remains **6:00 PM** (unchanged)",
        "type": "observation",
        "source": null
      },
      {
        "span": "Worked hours: Now properly reflects the full 9-hour day",
        "type": "observation",
        "source": null
      }
    ]
  }
]
```

Note on Step 4: "Worked hours: Now properly reflects the full 9-hour day" is observation (not reasoning_conclusion) because the agent is reporting it as a fact about the record — even though the tool result did not return worked_hours. This is a known over-claim pattern: the observation type still applies, and Stage 2 will verify it against the tool result.

Note on tool claims: if Step 3 instead said "the log_interaction tool requires a customer_id" or "there's no direct tool to log a note on a lead", those would be `reasoning_conclusion` — the agent's inference about tool capabilities, not a named business policy from codebook.md.

---

## Example C — summary block with table, each row/item is a separate claim

Input:
Step 5: The subtotal is $2,399.98 (2 × $1,199.99), and the total of $2,759.98 includes $360.00 in taxes. That all checks out.

Here's a summary of the quotation sent:

**Quotation S00017** has been created for **Fujita Kenji** ✅

| Item | Qty | Unit Price | Subtotal |
|------|:---:|:----------:|:--------:|
| Apple iPhone 16 Pro (IP16P-256) | 2 | $1,199.99 | $2,399.98 |
| **Tax** | | | $360.00 |
| **Total** | | | **$2,759.98** |

**Status**: Draft (quotation) — awaiting your confirmation to send to the customer.

**Note**: Since the order total exceeds $2,000, manager approval will be needed before we can confirm it. Would you like me to proceed with sending this quote to the customer?

Output:
```json
[
  {
    "step_id": 5,
    "claims": [
      {
        "span": "subtotal is $2,399.98 (2 × $1,199.99)",
        "type": "observation",
        "source": null
      },
      {
        "span": "total of $2,759.98 includes $360.00 in taxes",
        "type": "observation",
        "source": null
      },
      {
        "span": "That all checks out",
        "type": "reasoning_conclusion",
        "source": null
      },
      {
        "span": "Here's a summary of the quotation sent",
        "type": "non_actionable_text",
        "source": null
      },
      {
        "span": "Quotation S00017 has been created for Fujita Kenji",
        "type": "action_completion",
        "source": null
      },
      {
        "span": "Apple iPhone 16 Pro (IP16P-256) | 2 | $1,199.99 | $2,399.98",
        "type": "observation",
        "source": null
      },
      {
        "span": "Status: Draft (quotation)",
        "type": "observation",
        "source": null
      },
      {
        "span": "awaiting your confirmation to send to the customer",
        "type": "non_actionable_text",
        "source": null
      },
      {
        "span": "the order total exceeds $2,000",
        "type": "observation",
        "source": null
      },
      {
        "span": "manager approval will be needed before we can confirm it",
        "type": "constraint_or_policy",
        "source": "codebook.md"
      },
      {
        "span": "Would you like me to proceed with sending this quote to the customer?",
        "type": "recommendation",
        "source": null
      }
    ]
  }
]
```

Note on Step 5: Each table row with factual data (`subtotal`, `total with tax`, `item row`) is a separate observation claim — do not merge multiple rows into one span. The table header row and separator rows (`|------|`) contain no factual content and are skipped. `**Tax**` and `**Total**` rows are covered by the inline reasoning claims (`subtotal is $2,399.98...` and `total of $2,759.98...`) extracted from the prose.
