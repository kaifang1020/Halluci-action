# Task Expansion Design

## Objective

Scale Halluci-Action with tasks from Tau2-bench and, later, AppWorld while
preserving our research question: **does an agent's language faithfully match
its actions?**

External benchmarks provide tasks and executable environments. Halluci-Action
continues to provide the evaluated agents, trajectory contract, bidirectional
claim/action judges, and HAR metrics.

## Design Principles

1. **Evaluate our models.** Re-run each task with our agent models. Published
   Tau2/AppWorld trajectories are adapter fixtures, not experimental evidence.
2. **Separate execution from evaluation.** Benchmark runtimes generate
   trajectories; the Halluci-Action pass 1-4 pipeline evaluates them.
3. **Prevent ground-truth leakage.** Policies and tool schemas visible during
   execution go to the agent. Hidden scenarios, assertions, reference actions,
   and state audits remain evaluator-only.
4. **Preserve atomic evidence.** Store the full chronological dialogue and every
   tool/API call, result, argument, requestor, and affected object.
5. **Make interaction a controlled condition.** User simulation is an explicit
   experimental protocol, not an implicit property of a task.
6. **Compare like with like.** Compare agent models within the same task,
   user protocol, simulator configuration, and repeat scheme.
7. **Keep success and faithfulness distinct.** Native task reward measures task
   completion; Halluci-Action measures claim/action consistency and harmfulness.
8. **Use a versioned, runtime-neutral contract.** Tau2, AppWorld, and Odoo should
   emit the same canonical trajectory without changing the judges.

## Unified Pipeline

```text
External task + policy + initial state
                  |
             UserProtocol
                  |
     Halluci-Action AgentAdapter
         (our evaluated model)
                  |
       External tools/environment
                  |
        Raw interactive trajectory
                  |
        CanonicalTrajectoryAdapter
                  |
       Halluci-Action pass 1-4 eval
        |                       |
 claim -> action          action -> claim
 grounding audit          disclosure audit
        |                       |
 unsupported claims      undisclosed actions
                  |
             HAR severity
```

Only assistant text enters claim extraction. Only assistant-issued actions
enter the action denominator. User messages remain as context, and user-issued
actions must be retained but excluded from the evaluated agent's actions.

## Component Mapping

| Halluci-Action requirement | Tau2 counterpart | Evaluation role |
|---|---|---|
| User-visible task | Task and user scenario | Generates the request/dialogue |
| Agent-visible constraints | Domain policy | Prompt context and policy boundary |
| Action space | Environment tool schemas | Dynamically supplied callable tools |
| World state | Initial state and domain runtime | Executes and verifies actions |
| Agent action | Assistant tool call | Atomic action evidence |
| Action outcome | Tool result and state change | Grounding evidence |
| Agent claim | Assistant message | Atomic claim extraction |
| Interaction context | User-simulator messages | Information available at each turn |
| Task success | Reward criteria and assertions | Native benchmark metric |
| Hidden ground truth | Scenario, assertions, reference solution | Evaluator-only evidence |

"Dynamic tools" means that each domain's tool schemas are supplied through the
model API at runtime. It does not mean that the agent must discover tools by
searching the environment.

## Evaluation Contract

The canonical trajectory must support both audit directions:

1. **Claim to action:** extract atomic `action_intention` and
   `action_completion` claims, then verify that a grounding action exists and
   targets the correct object with compatible parameters and outcome.
2. **Action to claim:** inspect every agent action and verify that it was
   disclosed or justified by nearby assistant language.
3. **HAR severity:** combine the mismatch with policy, authorization, affected
   object, state transition, and impact.

Reference actions are supporting evidence, not automatically the only valid
execution path. A forbidden-action judgment requires explicit policy or task
constraints where possible; missing authorization or harm annotations must be
added as Halluci-Action evaluator metadata instead of inferred solely from the
reference solution.

## Interaction Protocols

`user_protocol` and `interaction_horizon` are separate variables:

- `user_protocol` describes how user information is provided.
- `interaction_horizon` records observed assistant turns, tool calls, and
  trajectory length.

The runner should support:

| Protocol | Purpose |
|---|---|
| `tau_llm_simulator` | Preserve Tau2's native adaptive multi-turn interaction |
| `full_information_single_turn` | Remove the user model and disclose permitted information initially |
| `scripted_user` | Preserve controlled multi-turn clarification without an LLM user |

These protocols change observability and task difficulty, so their scores must
be reported separately. Cross-protocol results are an ablation of user
simulation, not interchangeable samples from one benchmark condition.

Recorded user messages should not be replayed blindly across agents: simulator
responses depend on the preceding agent questions, making such trajectories
off-policy.

## Experimental Unit and Controls

The minimum experimental unit is:

```text
task x tested_agent x user_protocol x repeat
```

Within a condition, fix and record:

- tested-agent provider, model, prompt, temperature, and tool-call settings;
- user-simulator model, prompt, temperature, and seed when applicable;
- task/domain ID, policy version, initial state, and tool definitions;
- benchmark commit, runtime configuration, repeat ID, and termination reason;
- raw trajectory, native reward, and Halluci-Action judge provenance.

Multiple repeats are required for LLM user simulation because temperature zero
does not guarantee deterministic hosted-model behavior. Report variance rather
than treating the simulator as a transparent constant.

## Minimal Software Interfaces

1. `TaskLoader`: loads visible task data and evaluator-only ground truth.
2. `EnvironmentAdapter`: resets state, exposes tool schemas, executes calls,
   and optionally exports state snapshots/audits.
3. `AgentAdapter`: invokes the evaluated model with messages and runtime tool
   schemas, then normalizes text and tool calls.
4. `UserProtocol`: produces the initial request and subsequent user turns.
5. `TrajectoryRecorder`: stores lossless chronological events and provenance.
6. `CanonicalTrajectoryAdapter`: emits agent-only steps plus full interaction
   events for the current evaluators.
7. `GroundTruthProvider`: exposes hidden constraints and audits only to judges.
8. `EvaluationBridge`: runs pass 1-4, bidirectional matching, HAR severity, and
   native benchmark scoring.
9. `RunManifest`: records all configurations needed to reproduce a run.

## Expansion Order

1. **Tau2 first:** use its task, policy, simulator, tools, and environment to
   re-run our models; convert each new run to the canonical contract.
2. **User-simulation ablation:** run matched Tau2 tasks with at least the native
   simulator and full-information single-turn protocols.
3. **AppWorld second:** preserve AppWorld's runtime, but parse its API logs into
   atomic actions. A code-execution block is too coarse for claim/action audit.
4. **Scale only after validation:** manually audit a small matched sample before
   launching the full task/model/protocol matrix.

## Current Demo Status

The existing Tau2 Airline task 3 HTML converts a published Tau2 result into the
canonical schema and overlays a manual audit. Its original task agent was
Claude 3.7 Sonnet and its simulated user was GPT-4.1. It validates formatting
and visualization only; it is not a result for our evaluated models and must
not enter benchmark aggregates.

## Open Decisions

- Whether Tau2 policies contain enough explicit authorization and impact
  constraints for the full HAR severity taxonomy.
- Whether `full_information_single_turn` is sufficient as the main simulator
  ablation or whether a deterministic `scripted_user` is also required.
- The repeat count needed to estimate simulator-induced variance affordably.
- Which AppWorld API/task subset provides atomic, auditable actions comparable
  to the Tau2 and Odoo conditions.
