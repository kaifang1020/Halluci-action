# Decision Log

## 2026-07-21 — Select Tau2 end-to-end pilot

- Selected Direction A before running the interaction ablation.
- The user clarified the main hypothesis: interacting with a user increases the
  incidence of Halluci-Action.
- The evaluation unit is an atomic claim; multi-turn dialogue generalizes the
  evidence horizon and context of the existing single-turn formulation.
- Requirement status and execution support must remain separate judgments.
- DB checks, status assertions, tool results, and state deltas may corroborate a
  claim, but final state alone cannot prove that the evaluated agent performed
  the action because the state may preexist or be changed by the user simulator.
- Parked the single-turn ablation and severity stress subset until the pilot
  pipeline and judge are validated.

