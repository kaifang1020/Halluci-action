# Halluci-Action Research Package

This package implements the Halluci-Action experiment harness on top of the local Odoo research stack.

It includes:

- provider adapters for Anthropic, OpenAI, DeepSeek, Qwen, and Kimi
- a KL-aware shared tool registry
- an Odoo JSON-RPC tool executor
- a PostgreSQL-backed `halluci_audit` behavioral logger
- a multi-turn experiment runner with claim extraction

## Quick start

1. Start the local stack from the repository root:

```bash
cd odoo-research
./scripts/init.sh
```

2. Install the research dependencies:

```bash
python3 -m venv research/.venv
source research/.venv/bin/activate
pip install -r research/requirements.txt
```

3. Create your local environment file:

```bash
cp research/.env.example research/.env
```

4. Run a single experiment:

```bash
python3 -m research.harness run \
  --agent deepseek \
  --model deepseek-chat \
  --task-id task1 \
  --kl KL1 \
  --runs 1
```

## Notes

- The current registry exposes 81 tools across ten domains: sales, inventory, accounting, CRM, POS, HR, helpdesk, purchase, manufacturing, and project.
- All Odoo-side actions flow through [`gateway.py`](./gateway.py), which snapshots PostgreSQL before and after each tool call and writes `halluci_audit`.
- Run artifacts are saved under [`research/experiments/runs/`](./experiments/runs/).
- Claim extraction is currently regex-based and serves as a baseline until a judge-model stage is added.
- Repository-level setup and publishing notes are documented in `../README.md` and `../docs/GITHUB_PUSH_LOG_2026-03-28.md`.
