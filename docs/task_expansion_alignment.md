# Task Expansion Alignment Notes

Date: 2026-07-07

Goal: compare Halluci-Action's current task/evaluation pipeline with tau3/tau2-bench and AppWorld, then identify what must be adapted before importing or reusing their tasks.

Sources checked:

- Local code: `research/tasks.py`, `research/harness.py`, `research/gateway.py`, `research/tools/registry.py`, `research/eval/run_pipeline.py`
- tau3/tau2-bench: https://github.com/sierra-research/tau2-bench/tree/dev/tau3
- AppWorld: https://github.com/StonyBrookNLP/appworld

## 1. Current Halluci-Action Pipeline

Halluci-Action is not just a task runner. It is a claim/action audit harness over an Odoo ERP sandbox.

### Components

1. Task registry

   Source: `research/tasks.py`

   Current task schema:

   - `id`
   - `name`
   - `domain`
   - `difficulty`
   - `description`
   - `target_ha_types`
   - `system_constraints`
   - `user_instruction`
   - `ground_truth_steps`
   - `ambiguity_traps`
   - `data_requirements`

   The current benchmark is designed as `10 domains x 6 tasks = 60 tasks`, covering sales, inventory, accounting, CRM, POS, HR, helpdesk, purchase, manufacturing, and project. The important point is that `ground_truth_steps`, `ambiguity_traps`, and `system_constraints` are first-class evaluation metadata, not incidental documentation.

2. Prompt and knowledge condition

   Source: `research/tasks.py`, `research/codebook.md`, `research/config.py`

   The user sees only `user_instruction`. Constraints are exposed through one of two modes:

   - codebook mode: shared policy codebook plus domain section
   - explicit mode: per-task `system_constraints`

   The benchmark date/time is fixed through `BENCHMARK_CURRENT_DATE`, `BENCHMARK_CURRENT_TIME`, and `BENCHMARK_TIMEZONE`.

3. Tool registry

   Source: `research/tools/registry.py`

   Tools are structured `ToolSpec`s with:

   - canonical tool name
   - domain
   - summary
   - JSON schema parameters
   - key parameters
   - constraints
   - knowledge-level-dependent descriptions (`KL1`, `KL2`, `KL3`)

   This registry is also used by evaluation Pass 1b to map natural-language claims back to possible tools.

4. Runtime gateway and state audit

   Source: `research/gateway.py`

   Every tool call goes through `ToolGateway.execute()`, which:

   - snapshots mapped PostgreSQL tables before the call
   - executes the Odoo tool
   - snapshots after the call
   - computes row-level deltas
   - writes `halluci_audit`
   - returns an agent-visible result with audit-only fields redacted

   This is the strongest local component. It gives us objective evidence for "what changed" beyond the tool return value.

5. Trajectory format

   Source: `research/harness.py`

   Saved trajectory schema is `trajectory_v2_hidden_audit` with:

   - top-level task/model/provider metadata
   - visible benchmark context
   - `steps`
   - per-step assistant text
   - tool calls
   - redacted tool results
   - link to audit sidecar

   The audit sidecar stores full gateway results, pre/post claims, and state deltas.

6. Evaluation pipeline

   Source: `research/eval/run_pipeline.py`

   Current stages:

   - Pass 1a: extract atomic behavioral claims from assistant text
   - Pass 1b: map each claim to candidate tools from the registry
   - Pass 2: extract structured actions from trajectory tool calls
   - Pass 3 stage 1: local claim/action verification
   - Pass 3 stage 2: cross-step verification
   - Pass 4: constraint/codebook audit
   - Final compact JSON summary with gap and constraint-violation counts

### Local Invariant

Any external task source must eventually produce this minimal contract:

```text
TaskDefinition -> prompt/system policy -> structured tool calls -> trajectory_v2_hidden_audit -> actions + claims -> constraint-aware evaluation
```

If an imported task cannot support this contract, it can still be used as a baseline benchmark, but it is not yet a Halluci-Action task.

## 2. tau3 / tau2-bench Pipeline

tau3/tau2-bench is a simulated customer-service benchmark. The README describes each domain as specifying a policy, a set of tools, tasks, and optionally user tools. Available domains include `mock`, `airline`, `retail`, `telecom`, and `banking_knowledge`.

### Components

1. Domain package

   A tau2 domain has:

   - `data_model.py`
   - `user_data_model.py` when needed
   - `tools.py`
   - `user_tools.py` when needed
   - `environment.py`
   - `utils.py`

2. Data directory

   A tau2 domain stores:

   - `tasks.json`
   - optional `tasks_voice.json`
   - `split_tasks.json`
   - `policy.md`
   - `db.json` or `db.toml`
   - optional `user_db.json` or `user_db.toml`

3. Task model

   tau2 tasks include:

   - `id`
   - optional description
   - `user_scenario`
   - `evaluation_criteria`
   - optional `initial_state`

   `evaluation_criteria` can include expected actions, environment assertions, communication requirements, natural-language assertions, and reward basis.

4. Orchestrator

   tau2 supports:

   - half-duplex text evaluation
   - full-duplex voice evaluation
   - simulated user interaction
   - environment tools

5. New tau3-specific pieces

   The current tau3 branch adds:

   - `banking_knowledge`, a retrieval-oriented domain
   - configurable RAG/document search pipelines
   - voice full-duplex evaluation
   - task quality fixes

### Fit To Halluci-Action

Best fit:

- text half-duplex tasks from `retail`, `airline`, `telecom`, and possibly `banking_knowledge`
- domain `policy.md` as a source for our `codebook.md` or task `system_constraints`
- `evaluation_criteria.actions` and env assertions as seed material for `ground_truth_steps`
- ambiguous user/customer-service tasks as good sources for `ambiguity_traps`

Poor fit or not initially necessary:

- full-duplex voice tasks
- realtime/audio provider stack
- user simulator mechanics, unless we explicitly want multi-party interaction
- gym/RL interface
- leaderboard submission pipeline
- tau2's own scoring as the main score, because our goal is claim/action hallucination audit rather than task success alone

Integration difficulty: medium. tau2's world is closer to our current Odoo setup than AppWorld because it already frames tasks as policy-governed customer-service tool use. The main work is schema translation and evaluator evidence extraction.

## 3. AppWorld Pipeline

AppWorld is a controllable multi-app world for function calling and interactive coding agents. The README describes an engine with 9 day-to-day apps, 457 APIs, and 100+ database tables. Tasks are defined by supervisor, instruction, and initial state. Agents solve tasks by writing executable code that calls app APIs.

### Components

1. World and task loading

   Basic usage:

   - `load_task_ids(dataset)`
   - `AppWorld(task_id=task_id, experiment_name=...)`
   - `world.task.instruction`
   - `world.execute(code)`
   - `world.task_completed()`
   - `world.evaluate()`

2. Datasets

   Main splits:

   - `train`
   - `dev`
   - `test_normal`
   - `test_challenge`

3. Task data

   AppWorld task folders include:

   - `specs.json`: task instruction, datetime, supervisor info
   - task-specific DB diffs
   - `ground_truth`: setup, evaluation, solution, etc.

   Train/dev expose full ground truth. Test sets expose evaluation programs but not setup/solutions.

4. Runtime logs

   AppWorld output directories include:

   - DB diffs
   - evaluation report
   - `environment_io.md`
   - `api_calls.jsonl`
   - package/data version files

5. State control

   AppWorld supports checkpoints and state restore. This is useful for experiments but should be disabled or tightly controlled for fair Halluci-Action runs.

### Fit To Halluci-Action

Best fit:

- API-call logs as an alternative source for our Pass 2 actions
- DB diffs and final DB state as evidence analogous to `state_delta`
- train/dev task ground truth as seed material for `ground_truth_steps`
- tasks involving real app workflows, cross-app dependencies, and hidden state

Poor fit or not initially necessary:

- code-execution agent loop as the primary local agent protocol
- in-process FastAPI/TestClient mechanics
- AppWorld's supervisor/password helper model, except as hidden setup context
- arbitrary checkpoint save/load during agent execution
- test-set hidden setup/solution data for developing our task translation

Integration difficulty: high. AppWorld is more powerful but less aligned with our current tool-calling harness. Its agent action is "execute code" rather than "call one registered tool"; we would need to either wrap each AppWorld API as a Halluci `ToolSpec`, or treat each executed code block as a high-level action and parse `api_calls.jsonl` into atomic actions.

## 4. What We Should Preserve From External Tasks

For Halluci-Action, preserve only task elements that support claim/action hallucination analysis:

1. User-facing instruction

   Convert to `user_instruction`.

2. Domain policy and operational constraints

   Convert to either:

   - `system_constraints`
   - domain section in `codebook.md`
   - task-specific codebook rules

3. Initial database/world state

   Convert to:

   - Odoo seed records in `scripts/furnish_database.py`, or
   - external-world task fixture metadata if we add a non-Odoo backend

4. Expected actions

   Convert to `ground_truth_steps`, preserving ordering, required reads, required writes, and must-not-do constraints.

5. Environment assertions and final-state checks

   Convert to evaluator-side assertions, not agent-visible prompt text.

6. Ambiguity sources

   Convert to `ambiguity_traps`:

   - duplicate names
   - similar products/accounts
   - insufficient stock/balance
   - policy exception
   - read-only reporting task
   - task that requires asking for clarification

7. Tool/API docs

   Convert to `ToolSpec.summary`, parameter schema, and optional KL-specific disclosure.

## 5. What We Should Not Preserve Initially

Do not import these as first-class Halluci tasks in the first pass:

1. Voice/audio interaction

   It changes the communication protocol and creates unrelated failure modes.

2. User simulator loops

   Current Halluci-Action uses a single user instruction. Multi-turn simulated users are useful later but would require a new orchestrator contract.

3. External benchmark scoring as the primary metric

   Keep external success score as optional metadata. Our primary metric remains claim/action gaps and constraint violations.

4. Code execution as the only action

   If using AppWorld, parse actual API calls from logs. A single `world.execute(code)` action is too coarse for claim/action alignment.

5. Hidden test data translation

   Use train/dev or public task definitions for engineering. Avoid designing around hidden test solutions.

6. State rewind/checkpoints in agent loop

   This breaks realism and makes action audit harder.

## 6. Engineering Alignment Plan

### Phase A: Introduce a backend-neutral task schema

Add a local intermediate schema before touching Odoo-specific runtime:

```python
class ExternalTaskSpec(TypedDict):
    source: str                    # halluci | tau2 | appworld
    external_id: str
    id: str                        # local namespaced id, e.g. TAU2-RET-001
    domain: str
    difficulty: str
    user_instruction: str
    policy_text: str
    system_constraints: list[str]
    expected_actions: list[dict]
    final_state_assertions: list[dict]
    communication_requirements: list[str]
    ambiguity_traps: list[str]
    data_requirements: list[str]
    backend: str                   # odoo | tau2 | appworld
```

Then convert to the existing `TaskDefinition` only when the task is runnable through the current Odoo harness.

### Phase B: Add task importers, not direct registry edits

Recommended modules:

```text
research/external_tasks/
  __init__.py
  schema.py
  tau2_importer.py
  appworld_importer.py
  select_tasks.py
```

Importer responsibilities:

- load external metadata
- normalize task IDs
- extract instruction/policy/evaluation criteria
- classify required backend
- produce a task card for human review

Do not auto-register imported tasks into `research.tasks.TASKS` until they have a runnable backend and an evaluation mapping.

### Phase C: Decide backend strategy

There are two viable strategies:

1. Native Odoo translation

   Convert selected tau2/AppWorld task ideas into Odoo records/tools. This gives maximum compatibility with current gateway/audit/eval.

   Use this when:

   - task semantics map cleanly to sales/inventory/CRM/accounting/project
   - expected actions can be expressed with existing Odoo tools or small tool additions
   - final state can be checked through PostgreSQL snapshots

2. External backend adapter

   Keep tau2/AppWorld runtime intact, but add a `ToolGateway`-like adapter that emits Halluci-compatible trajectories and audit sidecars.

   Use this when:

   - task depends on external app semantics not worth porting to Odoo
   - task uses many APIs across apps
   - final-state evaluator is already available and reliable

Initial recommendation: start with native Odoo translation for tau2 retail/telecom-like tasks, and only prototype AppWorld through an external adapter.

### Phase D: Standardize action evidence

Current Pass 2 expects actions from trajectory tool calls. External adapters must emit the same logical row:

```json
{
  "action_id": 1,
  "trajectory_id": "...",
  "step_id": 1,
  "action_index": 1,
  "call_id": "...",
  "tool_name": "...",
  "parameters": {},
  "parameters_summary": "...",
  "status": "success",
  "result_summary": "...",
  "result_data": {}
}
```

For tau2:

- map environment tool calls to `tool_name`
- preserve tool parameters/results
- convert DB/env assertions into audit evidence where possible

For AppWorld:

- parse `api_calls.jsonl`
- use `app.api_name` as canonical `tool_name`
- store code block text separately as raw response/context
- use DB diffs as `state_delta`

### Phase E: Extend tool registry namespaces

Avoid name collisions by namespacing external tools:

```text
tau2_retail.cancel_order
tau2_airline.update_reservation
appworld.spotify.show_playlist_library
appworld.venmo.create_payment
```

Pass 1b currently maps claims using exact registry tool names. Namespacing keeps claim mapping stable and avoids confusing Odoo `cancel_order` with AppWorld or tau2 actions.

### Phase F: Add evaluator-side assertion adapter

External `evaluation_criteria` should become evaluator evidence:

- expected actions -> compare against Pass 2 actions
- env assertions -> compare against state deltas or final DB state
- communicate info / NL assertions -> compare against final assistant text
- reward basis -> metadata only

This should be separate from claim hallucination scoring. A task can succeed while containing unsupported claims, and a task can fail while not hallucinating.

### Phase G: Add task selection rubric

For each external task candidate, score:

- maps to current Odoo domain: yes/no
- requires new tools: none/small/large
- requires multi-turn user simulator: yes/no
- has explicit policy constraints: yes/no
- has ambiguous entities or hidden state: yes/no
- has mutating action risk: yes/no
- can produce state delta: yes/no
- can produce expected action list: yes/no

Only import tasks with:

- explicit operational constraint
- at least one verifiable action or observation
- objective state/log evidence
- manageable fixture setup

## 7. Recommended Near-Term Path

1. Use tau3 first.

   Pick 5-10 text tasks from retail/telecom/airline that resemble current ERP workflows. Convert them manually into local `TaskDefinition` candidates and add missing Odoo seed records/tools only when needed.

2. Add an external task card generator.

   Generate markdown cards from tau2/AppWorld metadata:

   - original instruction
   - policy snippets
   - expected actions/assertions
   - proposed Halluci domain
   - required tools
   - required fixtures
   - import decision

3. Keep AppWorld as a second-stage adapter.

   Prototype one AppWorld train/dev task by parsing `api_calls.jsonl` into Halluci Pass 2 actions. Do not try to port the whole code-execution environment into Odoo first.

4. Do not mix benchmark axes.

   Halluci-Action should remain about unsupported behavioral claims, over/under-claiming, substitution, premature claims, fabrication, and constraint violations. External benchmark task success is useful context, not the main metric.

## 8. Concrete Implementation Checklist

- [ ] Create `research/external_tasks/schema.py`
- [ ] Create `research/external_tasks/tau2_importer.py`
- [ ] Create `research/external_tasks/appworld_importer.py`
- [ ] Add a CLI command: `python -m research.external_tasks.select_tasks --source tau2 --domain retail`
- [ ] Emit review cards under `research/external_tasks/cards/`
- [ ] Add a namespaced external tool registry loader for Pass 1b
- [ ] Add an adapter that converts tau2/AppWorld logs to `trajectory_v2_hidden_audit`
- [ ] Add a small fixture/task smoke test under `research/experiments_v2/tests_traj/`
- [ ] Only after review, register selected tasks in `research.tasks.TASKS`

