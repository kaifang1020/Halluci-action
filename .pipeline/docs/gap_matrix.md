# Gap Matrix

| Question | Current evidence | Missing evidence | Minimum resolution | Status |
|---|---|---|---|---|
| Can Tau2 trajectories enter Halluci-Action losslessly? | Canonical adapter and Airline fixture demo exist | Fresh runs and requestor-attribution audit | One end-to-end original task with agent/user tool calls | selected |
| Is the atomic-claim judge valid in multi-turn dialogue? | Existing C2A supports cross-step evidence | Tau2-specific human labels and temporal edge cases | Manually audit pilot claims and their evidence pointers | open |
| Does interaction increase Halluci-Action incidence? | User hypothesis; no matched causal evidence yet | Matched protocols controlling task, agent, and exposure | Later multi-turn versus single-turn ablation | parked after pilot |
| Can required claims use multiple verification sources? | Canonical evaluator context retains reference actions, assertions, and native reward metadata | Current Tau2 requirement items expose mainly policy and reference steps | Add typed requirement and grounding evidence with provenance and conflict rules | open |
| Is HAR severity defined on original Tau2 tasks? | Policies and some task assertions provide risk evidence | Coverage and empty-denominator behavior are unknown | Report per-source coverage and N/A denominators in pilot | open |

