# Agent Handoff

## Active Direction

Run Direction A: a small original-task Tau2 pilot with a fixed cooperative user
simulator and atomic-claim Halluci-Action evaluation.

## Immediate Next Work

1. Define a typed evidence bundle for each atomic claim:
   requirement oracles, execution trace, tool result, pre/post state, final
   assertions, user-side actions, and provenance.
2. Update the Tau2 requirement-item builder so it does not drop
   `env_assertions`, `nl_assertions`, `communicate_info`, `initial_state`, and
   requestor attribution.
3. Select 6--8 action-bearing tasks with predeclared properties.
4. Run one smoke task, inspect every claim/action edge manually, and only then
   launch the pilot matrix.

## Guardrails

- Do not infer agent execution from final state alone.
- Do not treat reference actions as the only valid path unless their binding is
  explicitly required.
- Keep user tool calls in chronological context and out of the assistant action
  denominator.
- Record assertion results, not only assertion specifications.
- Treat unsupported required claims as the join of two independent labels:
  `requirement_status == required` and `c2a_verdict == not_supported`.

