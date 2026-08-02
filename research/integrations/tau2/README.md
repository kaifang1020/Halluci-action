# Tau2 Integration Contract Demo

This directory defines the first versioned boundary between Tau2 result files
and the Halluci-Action claim/action evaluation pipeline.

## Contract decisions

- `steps` is an agent-only projection with the existing
  `assistant_text` / `tool_calls` / `tool_results` keys. Current claim extraction
  and grounding code can read this projection.
- `events` retains the chronological user, assistant, and tool messages. User
  tool calls stay here and never enter the agent action denominator.
- `agent_context` contains information available to the evaluated agent, such
  as the domain policy.
- `evaluator_context` contains hidden user-simulator instructions, native
  rewards, assertions, and the Tau2 reference solution. It must never be sent
  to the evaluated agent.
- Tau2 reference actions are `reference_only` unless `ACTION` appears in the
  task's `reward_basis`.
- Tau2 result files do not contain Halluci-Action's per-action database audit.
  `audit_file` and `audit_record_index` therefore remain null in this demo.

## Run the included demo

```bash
python -m research.integrations.tau2.demo \
  --results research/integrations/tau2/fixtures/minimal_tau2_result.json \
  --task-id demo-1 \
  --trial 0 \
  --out /tmp/tau2_demo_canonical.json \
  --schema-out /tmp/halluci_action_canonical_trajectory_v1.schema.json
```

Run the adapter tests with:

```bash
python -m unittest research.integrations.tau2.tests.test_adapter
```

## Generate the audit visualization

The Airline task 3 demo audit is stored as structured JSON and rendered into a
standalone HTML report:

```bash
python -m research.integrations.tau2.generate_demo_audit_html
```

Open `airline_task3_demo_audit.html` directly in a browser. The report supports
print/PDF output and deep links to `#overview`, `#evidence`, `#timeline`, and
`#contract`.

For a real Tau2 result, point `--results` at a file under
`data/tau2/results/` in a Tau2 checkout. No Tau2 Python installation is
required because the adapter consumes the serialized result contract. Published
result files usually omit tool definitions; an exported JSON list from
`Environment.get_info(include_tool_info=True)` can be supplied with
`--tool-definitions`.
