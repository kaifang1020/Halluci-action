# Selected Research Direction

## Direction

Direction A: run an end-to-end Halluci-Action pilot on original Tau2 tasks under
a fixed, strong cooperative user simulator. Multi-turn interaction is treated
as a generalization of the existing single-turn setting, not as a different
evaluation object.

## Core Question

Can original Tau2 tasks be executed, converted into the canonical trajectory
contract, and scored reliably at the atomic-claim level by the bidirectional
judge? The motivating hypothesis for the later matched comparison is that
multi-turn user interaction increases Halluci-Action incidence relative to the
single-turn condition.

## Why This Is Worth Doing

- It tests whether HAR transfers from the Odoo single-turn sandbox to an
  adaptive conversational environment.
- It separates native task completion from claim--action faithfulness.
- It establishes the infrastructure and annotation protocol needed for a later
  multi-turn versus single-turn comparison without claiming that comparison has
  already been run.

## Evidence Base

- `research/integrations/tau2/` already contains a canonical adapter and one
  published-trajectory Airline demo.
- `docs/task_expansion_design.md` defines user protocol as a controlled
  experimental condition and excludes user-issued tools from the evaluated
  agent's action denominator.
- The current claim/action evaluator already supports atomic action-intention
  and action-completion claims and cross-step evidence.

Evidence maturity is medium: the contract and demo exist, but fresh reruns,
Tau2-specific human judge validation, simulator variance, and severity evidence
coverage remain missing.

## Novelty Threats

- The existence and magnitude of an interaction effect are unverified.
- A fixed strong user only supports claims conditional on that simulator.
- Higher HAR in multi-turn trajectories may be caused mechanically by more
  claims/actions unless matched analyses control exposure and trajectory length.

## Minimum Experiment

- Preselect 6--8 action-bearing original Tau2 tasks across read, mutation,
  clarification, confirmation, and user-side-action cases.
- Fix one calibrated cooperative user simulator configuration.
- Run two tested agents and three repeats per task after environment reset.
- Preserve full dialogue, assistant and user tool requestors, tool results,
  state/status assertions, native reward, and termination metadata.
- Score atomic claims with C2A, assistant actions with A2C, and report native
  reward, directional gaps, HAR, HAR severity, and policy violations.
- Manually audit all pilot units or, at minimum, all gaps plus a stratified
  sample of supported units.

## Required Baselines

- Native Tau2 reward/assertions.
- C2A-Gap and A2C-Gap reported separately from combined HAR.
- A clean/supportable trajectory control so the judge cannot obtain apparent
  accuracy by predicting gaps everywhere.
- The single-turn matched comparison is parked for the next stage, but the
  `user_protocol` field must be retained now.

## Risks And Kill Criteria

- Stop scaling if assistant and user actions cannot be attributed losslessly.
- Stop scaling if final-state assertions cannot distinguish agent-caused changes
  from initial state or user-side actions.
- Revise the evidence contract if human review shows that DB/status assertions
  systematically overturn trace-only C2A verdicts.
- Do not use HAR severity when required/forbidden denominators are absent; report
  the case as not applicable with evidence-coverage counts.

## Next Actions

- Extend the pilot judge input with typed multi-source evidence while preserving
  the separation between requirement classification and execution grounding.
- Select the 6--8 pilot tasks using a preregistered task-property rubric.
- Freeze the user-simulator qualification rubric and run manifest fields.
- Run one smoke trajectory before launching the pilot matrix.

## Rejected Or Parked Directions
