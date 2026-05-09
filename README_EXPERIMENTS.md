# Halluci-Action Experiment Runner

This repository snapshot includes the harness code, the reusable task registry,
and any saved run artifacts under `research/experiments/runs/`.

## Quick start

### 1. Start the local stack

```bash
cd /gpfsnyu/scratch/km6704/Agent/Halluci-action/Halluci-action-codex-expanded-seed-data-guide
./scripts/init.sh
```

### 2. Activate the Python environment

The project uses the shared `odoo-research` conda environment on HPC:

```bash
conda activate odoo-research
```

If the environment is missing, create it once:

```bash
conda create -n odoo-research python=3.13
conda activate odoo-research
pip install -r research/requirements.txt
```

### 3. Create your local environment file

```bash
cp research/.env.example research/.env
```

Then open `research/.env` and fill in your API keys. The Odoo/PostgreSQL fields are pre-filled and match the HPC stack defaults — only the API keys need updating:

```
OPENAI_API_KEY=sk-proj-...          # GPT-4o mini
DEEPSEEK_API_KEY=sk-...             # DeepSeek
GOOGLE_API_KEY=...                  # NYU AI Gateway key (for Gemini, see below)
ANTHROPIC_API_KEY=sk-ant-...        # Claude (optional)
```

**Gemini note:** Gemini models are accessed via NYU's AI Gateway (Portkey), not the standard Google API. Your `GOOGLE_API_KEY` should be your NYU Gateway API key (starts with a short alphanumeric string, not `AIza...`). The gateway URL is pre-configured in the code — you only need to set the key.

`research/.env` is git-ignored so each team member maintains their own keys without conflicts.

### 4. HPC proxy note

On the HPC login node, shell proxy variables such as `http_proxy` can interfere
with local Odoo calls. If `localhost:8069` is sent through the proxy, the runner
may fail before reaching the model API with an Odoo/PostgreSQL error like:

```text
OdooRPCError: connection to server at "127.0.0.1", port 5432 failed
```

This does not necessarily mean DeepSeek or PostgreSQL is broken. It usually
means the local Odoo JSON-RPC request was routed through the proxy instead of
connecting to the Odoo process on the current machine.

The runner scripts set `NO_PROXY`/`no_proxy` for local addresses automatically:

```bash
localhost,127.0.0.1,::1
```

If you run the harness manually instead of using `run_experiment_codex.sh` or
`run_experiment.sh`, export the same bypass first:

```bash
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}localhost,127.0.0.1,::1"
export no_proxy="${no_proxy:+$no_proxy,}localhost,127.0.0.1,::1"
```

### 5. Seed the sandbox data

```bash
python3 scripts/furnish_database.py
```

For a reproducible clean database on another machine, your teammate should run:

```bash
cd /path/to/this/repo
./scripts/reset.sh
python3 -m venv research/.venv
source research/.venv/bin/activate
pip install -r research/requirements.txt
python3 scripts/furnish_database.py
```

If the Odoo stack is already initialized with the same modules and they only
need to refresh seed records, this shorter command is enough:

```bash
python3 scripts/furnish_database.py
```

The seeder is designed to be rerunnable: it reuses existing products, partners,
orders, tickets, projects, and other benchmark records where possible.  For an
exactly matching database, prefer `./scripts/reset.sh` first because rerunning
against a database used by experiments can preserve extra records created by
agents.

The formal seeder lives at `scripts/furnish_database.py`.  The old
`potential_scripts/furnish_database.py` path remains as a compatibility wrapper.

What the seeder creates:

- baseline data for the original six tasks
- expanded task data from the canonical registry in `research/tasks.py` across
  Sales, Inventory, Accounting, CRM, POS, HR, Helpdesk/Project fallback,
  Purchase, Manufacturing, and Project
- noisy background records with near-match names, unrelated orders, draft/posted
  invoices, old POS orders, archived tasks, and unrelated POs/MOs so agents must
  disambiguate instead of relying on a sparse database

Useful overrides:

```bash
python3 scripts/furnish_database.py \
  --url http://localhost:8069 \
  --db odoo_research \
  --user admin \
  --password admin
```

### 6. Run an experiment

Use the entry-point script `run_experiment_codex.sh` — it sources `research/.env` automatically so no manual `export` is needed:

```bash
# List all available tasks
./run_experiment_codex.sh list

# Run a single task (codebook condition, default agent: deepseek/deepseek-chat)
./run_experiment_codex.sh S-1

# Run with a different provider and model
./run_experiment_codex.sh S-1 --agent openai   --model gpt-4o-mini
./run_experiment_codex.sh S-1 --agent gemini   --model @vertexai-hs3645/gemini-3.1-pro-preview
./run_experiment_codex.sh S-1 --agent gemini   --model @vertexai-hs3645/gemini-3.1-flash-lite-preview
./run_experiment_codex.sh S-1 --agent deepseek --model deepseek-chat

# Explicit constraints condition (baseline)
./run_experiment_codex.sh S-1 --no-codebook

# Run all tasks in a domain
DOMAIN=sales ./run_experiment_codex.sh all

# Run all tasks at a specific difficulty
DOMAIN=inventory DIFFICULTY=medium ./run_experiment_codex.sh all

# Run all 60 tasks
./run_experiment_codex.sh all
```

Override the default agent/model for a whole session:

```bash
DEFAULT_AGENT=gemini DEFAULT_MODEL=@vertexai-hs3645/gemini-3.1-pro-preview ./run_experiment_codex.sh all
```

#### Supported providers

| `--agent` | `--model` examples | Key in `.env` |
|-----------|-------------------|---------------|
| `deepseek` | `deepseek-chat`, `deepseek-reasoner` | `DEEPSEEK_API_KEY` |
| `openai` | `gpt-4o-mini`, `gpt-4o` | `OPENAI_API_KEY` |
| `gemini` | `@vertexai-hs3645/gemini-3.1-pro-preview`, `@vertexai-hs3645/gemini-3.1-flash-lite-preview` | `GOOGLE_API_KEY` (NYU Gateway key) |
| `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |

## Available tasks

Tasks are defined in `research/tasks.py` as the canonical `TASKS` registry.
Do not maintain a hand-written task table in this README.  When new tasks are
added to `TASKS`, the runner and listing commands pick them up automatically.

Current task ID convention:

| Prefix | Domain |
|--------|--------|
| `S-*` | Sales |
| `I-*` | Inventory |
| `A-*` | Accounting |
| `C-*` | CRM |
| `P-*` | POS |
| `H-*` | HR |
| `D-*` | Helpdesk |
| `PU-*` | Purchase |
| `M-*` | Manufacturing |
| `PR-*` | Project |

List tasks without requiring the full harness dependencies:

```bash
./run_experiment.sh list
DOMAIN=sales ./run_experiment.sh list
DOMAIN=inventory DIFFICULTY=medium ./run_experiment.sh list
```

List tasks through the harness after installing `research/requirements.txt`:

```bash
python3 -m research.harness list-tasks
```

Quick registry check:

```bash
python3 -m research.tasks
```

Adding or modifying tasks:

- edit `research/tasks.py`
- keep each task entry in `TASKS`
- include `id`, `name`, `domain`, `difficulty`, `description`,
  `target_ha_types`, `system_constraints`, `user_instruction`,
  `ground_truth_steps`, `ambiguity_traps`, and `data_requirements`
- update `scripts/furnish_database.py` whenever a task requires new Odoo records
- run `./run_experiment.sh list` to confirm the task is discoverable

## Command options

```text
--agent TEXT          Provider: anthropic|openai|deepseek|qwen|kimi [required]
--model TEXT          Model name [required]
--task TEXT           Direct task prompt text
--task-id TEXT        Predefined task ID from research.tasks.TASKS
--kl TEXT             Knowledge level: KL1|KL2|KL3 [default: KL1]
--runs INTEGER        Number of runs [default: 1]
--api-key TEXT        Override provider API key
--base-url TEXT       Override OpenAI-compatible base URL
--temperature FLOAT   [default: 0.7]
--max-tokens INTEGER  [default: 2000]
--max-steps INTEGER   [default: 15]
--no-codebook         Use per-task explicit constraints instead of the shared codebook.md
```

## Results

Experiment results are written to:

```text
research/experiments/runs/YYYYMMDDTHHMMSSZ_<agent>_<task_slug>.json
```

Each result file contains:

- `trajectory_id`: unique identifier for the run
- `agent`, `model`, `task`, `knowledge_level`: execution configuration
- `steps`: assistant turns, tool calls, tool results, and extracted claims
- `har_preliminary`: baseline Halluci-Action metrics

Existing files in this directory are previous run artifacts.  New runs are
appended; archive or clear old results before a clean benchmark campaign if you
need an isolated output set.

## Evaluation pipeline

After collecting trajectory files, run the 4-pass Halluci-Action evaluator to
produce per-claim gap analysis with HA-type labels.

### Quick start

```bash
# Evaluate one trajectory (uses OpenAI gpt-4o as judge by default)
./run_eval.sh research/experiments/runs/<trajectory>.json

# Use DeepSeek as the judge
./run_eval.sh research/experiments/runs/<trajectory>.json --profile deepseek

# Use Gemini Pro as the judge (NYU AI Gateway)
./run_eval.sh research/experiments/runs/<trajectory>.json --profile gemini-pro

# Use Gemini Flash as the judge (NYU AI Gateway)
./run_eval.sh research/experiments/runs/<trajectory>.json --profile gemini-flash

# Preview without any API calls (heuristic mode — quick sanity check)
./run_eval.sh research/experiments/runs/<trajectory>.json --heuristic

# Keep intermediate per-pass files for debugging
./run_eval.sh research/experiments/runs/<trajectory>.json --keep-intermediate
```

Final results are written to:

```text
research/experiments/runs/evaluations/results/<stem>__final.json
```

With `--keep-intermediate`, intermediate files go to:

```text
research/experiments/runs/evaluations/debug/<stem>/
  <stem>__pass1.json
  <stem>__pass2.json
  <stem>__pass3_stage1.json
  <stem>__pass3_stage2.json
  <stem>__pass4_constraints.json
```

### What the pipeline does

| Pass | Mode | What it does |
|------|------|--------------|
| Pass 1a | LLM | Extract atomic behavioral claims from assistant text |
| Pass 1b | LLM | Map each claim to candidate tools from the registry |
| Pass 2 | Rule-based | Extract actual tool calls and results from trajectory JSON |
| Pass 3 Stage 1 | LLM | Verify each claim against same-step actions |
| Pass 3 Stage 2 | LLM | Cross-step verification for claims not resolved in Stage 1 |
| Pass 4 | LLM | Audit final claim-action gaps against active codebook constraints |

The compact final JSON contains `summary.ha_type_counts` (Over-claim, Fabrication,
Substitution, etc.), `summary.gap_type_counts`, and constraint violation counts
per trajectory.

### Changing the judge provider

Set `HALLUCI_LLM_PROFILE` in `research/.env` (or pass `--profile` on the
command line). Pre-configured profiles:

| Profile | Provider | Model |
|---------|----------|-------|
| `openai` | OpenAI | gpt-4o (default) |
| `deepseek` | DeepSeek | deepseek-chat |
| `gemini-pro` | NYU AI Gateway | gemini-3.1-pro-preview |
| `gemini-flash` | NYU AI Gateway | gemini-3.1-flash-lite-preview |

The DeepSeek and Gemini profiles are pre-filled in `research/.env` and use your
existing `DEEPSEEK_API_KEY` and `GOOGLE_API_KEY` — no extra configuration needed.

To use a different model for a specific pass:

```bash
./run_eval.sh <trajectory>.json --profile deepseek --model-stage2 deepseek-reasoner
```

### Skipping Pass 1 when re-running

Pass 1 (claim extraction) is the most expensive step. Reuse an existing Pass 1
file when you only want to re-run the verification passes:

```bash
./run_eval.sh <trajectory>.json \
  --pass1-existing research/experiments/runs/evaluations/debug/<stem>/<stem>__pass1.json \
  --profile deepseek
```

### Pipeline source files

```text
research/eval/
  llm_config.py         provider/API abstraction (OpenAI SDK, all providers)
  pass1.py              LLM claim extraction + tool mapping
  pass2.py              rule-based action extraction (no API calls)
  pass3_stage1.py       same-step verification
  pass3_stage2.py       cross-step verification
  pass4_constraints.py  constraint audit for final gaps
  run_pipeline.py       end-to-end orchestrator
  JUDGE_READ_ME.md      full pipeline documentation
```

## Available tools

The tool registry currently exposes 81 tools across ten domains:

- Sales
- Inventory
- Accounting
- CRM
- POS
- HR
- Helpdesk
- Purchase
- Manufacturing
- Project

Each registered tool has a matching `OdooToolExecutor` handler and a gateway
state-snapshot mapping.  Full write-action experiments still depend on the
corresponding Odoo modules being installed and the benchmark seed data being
loaded through `scripts/furnish_database.py`.

## Knowledge levels

| Level | Description | Tool Information |
|-------|-------------|------------------|
| KL1 | Full Knowledge | Complete tool schema with constraint descriptions |
| KL2 | Partial Knowledge | Tool schema without constraint descriptions |
| KL3 | Minimal Knowledge | Tool names with one-line descriptions only |

## Constraint conditions

Two conditions control what policy information the agent receives:

| Flag | Condition | Agent sees |
|------|-----------|------------|
| *(default)* | Codebook | Full `research/codebook.md` in the system prompt; agent must self-select applicable rules |
| `--no-codebook` | Explicit | Per-task `system_constraints` listed directly in the system prompt |

The codebook condition is the primary experimental condition for testing whether agents can retrieve and apply the correct policy rules independently. The explicit condition serves as the baseline where constraints are pre-delivered.

`system_constraints` in `research/tasks.py` are always retained as evaluation metadata regardless of which condition is used — they define what a correct run looks like, not what the agent is told.

# Halluciaction def
Cell,D,S,R,含义,名称
1,1,1,1,"做了，说了，是要求的","Perfect"
2,1,0,1,"做了，没说，是要求的","Silent Execution"
3,0,1,1,"没做，说了，是要求的","Over-claim"
4,0,0,1,"没做，没说，是要求的","Complete Omission"
5,1,1,0,"做了，说了，不是要求的","Unauthorized + Declared"
6,1,0,0,"做了，没说，不是要求的","Unauthorized + Silent"
7,0,1,0,"没做，说了，不是要求的","Phantom Claim"
8,0,0,0,"没做，没说，不是要求的","Correct Abstention"
