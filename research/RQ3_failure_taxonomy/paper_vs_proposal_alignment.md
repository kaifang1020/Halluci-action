# RQ3 Paper–Proposal Alignment: Unsupported Claims vs. Silent Execution

## Executive finding

The current paper section analyzes only the **claim-anchored** side of
halluci-action: 127 genuine unsupported action claims. The taxonomy proposal
contains the same three claim-side mechanisms, but adds the missing
**action-anchored** side: 608 undisclosed executions. The counts reconcile
exactly:

```text
86 C1 + 33 C2 + 8 C3 = 127 unsupported claims
127 unsupported claims + 608 C4 undisclosed executions = 735 genuine instances
```

Thus, the proposal is a strict extension of the paper's current RQ3 rather than
a competing taxonomy. The main paper gap is that RQ3 explains only 17.3% of the
observed halluci-actions and omits C4, which accounts for 82.7% (608/735).

## One-to-one mapping

| Current paper RQ3 | Proposal class | Same evidence | What the proposal adds |
| --- | --- | ---: | --- |
| Finding 1: Narration outruns execution | C1 — Unexecuted Commitment | 86 | Formal gate `π(c)=∅`; separates Abandoned Intention from Fabricated Completion. |
| Finding 2: Intended actions lose their referents | C2 — Misgrounded Execution | 33 | Formal grounding failure; flags the mutation-capable subset as higher risk. |
| Finding 3: Attempts are mistaken for accomplishments | C3 — Unverified Outcome | 8 | Separates False Success from Unverified Assertion. |
| **Missing from RQ3** | **C4 — Undisclosed Execution** | **608** | Formal reverse gate `κ(b)=∅`; introduces a risk overlay for silent actions. |

## What is already consistent

1. **Same causal ordering.** Both versions explain forward gaps at the same
   transitions: plan-to-execution (C1), language-to-arguments (C2), and
   tool-result-to-report (C3).
2. **Same counts and examples.** The paper's 86/33/8 partition exactly matches
   proposal C1/C2/C3. The DeepSeek CRM referent error and GPT-4o-mini S-5 false
   delivery success are shared examples.
3. **Same interventions.** Commitment tracking maps to C1, entity verification
   to C2, and postcondition checking to C3.
4. **Same formal foundation.** The proposal opens the paper's binary
   `Con(c)=0` into C1–C3 and maps the paper's reverse criterion `κ(b)=∅`
   directly to C4.

## What differs or is missing

### 1. Scope: the paper says RQ3 studies halluci-action, but analyzes only forward gaps

The RQ3 opening states that RQ1 establishes unsupported action claims and then
codes only those claims. This narrows the question from bidirectional HAR to
claim-side over-claiming. It conflicts with RQ1 and RQ2, where silent action is
both the dominant direction and the main reason HAR exceeds factual
hallucination metrics.

**Recommended correction:** introduce RQ3 as a taxonomy over both projections:
127 claim-anchored gaps (C1–C3) and 608 action-anchored gaps (C4).

### 2. Granularity: the proposal names subtypes that the paper currently merges

- Paper Finding 1 merges prospective abandoned intentions and retrospective
  fabricated completions; proposal C1 distinguishes them.
- Paper Finding 3 foregrounds failed tool outcomes; proposal C3 also includes
  unverified entity/result assertions.
- Paper Finding 2 mentions state-changing risk but does not report the proposed
  mutation-risk subset.

These subtype names are useful diagnostics, but they should remain secondary to
the four formal gates so the main taxonomy stays compact.

### 3. Silent-execution mechanism is absent from the paper

The proposal attributes C4 to an **output-channel/pragmatics gap**: the model
treats tool calls as private reasoning rather than behavior that must be
disclosed. This mechanism has no counterpart in the current RQ3 text and no
paired safeguard.

**Recommended safeguard:** trace-to-report reconciliation. Before returning,
the agent should compare its executed-action ledger with its user-facing report
and either disclose each policy-relevant action or explicitly justify why a
low-risk read is omitted.

### 4. Terminology is not yet harmonized

The paper alternates among *silent action*, *did-not-said*, *reverse gap*, and
*undisclosed action*. The proposal uses *Undisclosed Execution (C4)* and then
three subtype labels. A clean hierarchy would be:

```text
Formal class: C4 Undisclosed Execution
Metric name: A2C-Gap / did-not-say rate
Risk descriptors: required, allowed-supporting, unnecessary, forbidden;
                  read, mutation attempt, realized mutation
```

## Silent-execution audit: proposal claims that need revision

The proposal's current C4 risk list is intuitive but does not cleanly match the
annotations or the formal metric.

### A. “Every consequential action” is narrower than the implemented denominator

The proposal defines C4 using “every consequential action,” but A2C-Gap uses
**all 2,835 executed tool actions**, including benign reads. The 608 C4 cases
therefore include any undisclosed tool call, not only consequential actions.

### B. The three C4 subtypes are not exhaustive under the four-way requirement labels

Among the 608 undisclosed actions:

| Requirement status | Count | Share of C4 |
| --- | ---: | ---: |
| Required | 224 | 36.8% |
| Allowed supporting | 287 | 47.2% |
| Unnecessary | 80 | 13.2% |
| Forbidden | 17 | 2.8% |

The proposal names forbidden mutations, permitted mutations, and benign reads.
That scheme leaves **unnecessary reads** and **forbidden but non-mutating or
failed calls** without a clear subtype. Requirement status should therefore be
an orthogonal risk attribute, not encoded into three supposedly exhaustive C4
classes.

### C. “Executed mutation” currently conflates invocation, success, and state change

Of the 608 undisclosed actions, 12 are annotated as mutation-type tool calls and
596 as non-mutations. Only 3 of the 12 mutation-type calls return `status=success`;
among the 17 silent forbidden calls, only one mutation-type call succeeds. The
proposal's DeepSeek-Reasoner I-1 example calls a failed `process_refund` attempt
a hidden state mutation, although the tool returns an error and the annotation
records `is_mutation=false`.

Use the following distinctions:

```text
silent invocation       = tool call has no disclosing claim
silent mutation attempt = undisclosed call to a mutation-capable tool
silent realized mutation = successful call plus confirmed state delta
```

“Covert violation” can safely denote any silent forbidden invocation, but the
paper should reserve “hidden state mutation” for cases with a confirmed state
change, such as Qwen C-3 marking the wrong opportunity as won.

## Recommended RQ3 narrative

1. Introduce the four-gate faithfulness chain and report 735 genuine instances.
2. Present C1–C3 compactly as the 127 unsupported-claim mechanisms already in
   the paper.
3. Add C4 as the dominant class: 608/735 (82.7%) undisclosed executions.
4. Explain that C4 frequency is dominated by reads, while risk is concentrated
   in silent forbidden attempts and confirmed hidden mutations.
5. Close with four safeguards: commitment tracking, entity verification,
   postcondition checking, and trace-to-report reconciliation.

This structure preserves the paper's current evidence while making RQ3 match
the bidirectional definition of HAR used throughout the rest of the paper.
