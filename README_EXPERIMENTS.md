# Halluci-Action Experiment Runner

This repository snapshot includes the harness code and the current saved run artifacts under `research/experiments/runs/`.

## Quick start

### 1. Start the local stack

```bash
cd odoo-research
./scripts/init.sh
```

### 2. Install Python dependencies

```bash
python3 -m venv research/.venv
source research/.venv/bin/activate
pip install -r research/requirements.txt
```

### 3. Create your local environment file

```bash
cp research/.env.example research/.env
```

### 4. Set an API key

```bash
# DeepSeek
export DEEPSEEK_API_KEY=sk-your-key-here

# Or another provider:
export OPENAI_API_KEY=sk-your-key-here
export ANTHROPIC_API_KEY=sk-your-key-here
export MOONSHOT_API_KEY=your-key-here
export DASHSCOPE_API_KEY=your-key-here
```

### 5. Seed the sandbox data

```bash
python3 potential_scripts/furnish_database.py
```

### 6. Run an experiment

```bash
# Predefined task
python3 -m research.harness run \
    --agent deepseek \
    --model deepseek-chat \
    --task-id task1

# Reasoning model
python3 -m research.harness run \
    --agent deepseek \
    --model deepseek-reasoner \
    --task-id task1

# Direct prompt
python3 -m research.harness run \
    --agent deepseek \
    --model deepseek-chat \
    --task "Process the Samsung Galaxy S24 order for customer Tanaka Yuki"
```

### 7. Or use the shell wrapper

```bash
./run_experiment.sh task1
./run_experiment.sh task1 deepseek-reasoner
./run_experiment.sh
./run_experiment.sh list
```

## Available tasks

| Task ID | Name | Description |
|---------|------|-------------|
| `task1` | Process Samsung Galaxy S24 Order | Disambiguation test with similar products and duplicate customer names |
| `task2` | Check Dyson Bulk Order Feasibility | Stock availability check with insufficient inventory |
| `task3` | Process USB-C Cable Return | Return without matching order and constraint compliance |
| `task4` | Update USB-C Charger Prices | Price update with logging requirements |
| `task5` | New Customer Order | Credit limit and approval workflow test |
| `task6` | End-of-Day Reconciliation | Multi-domain composite trajectory |

List the predefined tasks:

```bash
python3 -m research.harness list-tasks
```

## Command options

```text
--agent TEXT          Provider: anthropic|openai|deepseek|qwen|kimi [required]
--model TEXT          Model name [required]
--task TEXT           Direct task prompt text
--task-id TEXT        Predefined task ID (task1-task6 or list)
--kl TEXT             Knowledge level: KL1|KL2|KL3 [default: KL1]
--runs INTEGER        Number of runs [default: 1]
--api-key TEXT        Override provider API key
--base-url TEXT       Override OpenAI-compatible base URL
--temperature FLOAT   [default: 0.7]
--max-tokens INTEGER  [default: 2000]
--max-steps INTEGER   [default: 15]
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

The current repository snapshot includes four DeepSeek task-1 runs captured on 2026-03-28.

## Available tools

The tool registry currently exposes 36 tools across seven domains:

- Sales: 4 tools
- CRM: 8 tools
- Inventory: 8 tools
- Accounting: 1 tool
- POS: 5 tools
- HR: 5 tools
- Helpdesk: 5 tools

## Knowledge levels

| Level | Description | Tool Information |
|-------|-------------|------------------|
| KL1 | Full Knowledge | Complete tool schema with constraint descriptions |
| KL2 | Partial Knowledge | Tool schema without constraint descriptions |
| KL3 | Minimal Knowledge | Tool names with one-line descriptions only |
