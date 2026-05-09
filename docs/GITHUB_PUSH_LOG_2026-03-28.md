# GitHub Push Log (2026-03-28)

## Purpose

This log documents the repository state prepared for pushing `odoo-research/` to:

`https://github.com/kaifang1020/Halluci-action.git`

The intended repository root is this directory itself. Nothing outside `odoo-research/` should be committed.

## Publication scope

The prepared snapshot includes:

- the local Odoo stack definition in `docker-compose.yml` and `odoo.conf`
- the shell entrypoints in `scripts/`
- the sandbox data seeding and design materials in `potential_scripts/`
- the full Python research package in `research/`
- the saved run outputs in `research/experiments/runs/`
- the project documentation in `README.md`, `README_EXPERIMENTS.md`, and `docs/`

The prepared snapshot excludes:

- local secrets such as `research/.env`
- virtual environments such as `research/.venv/`
- Python caches such as `__pycache__/`
- macOS AppleDouble artifacts such as `._*`
- the unused top-level `experiments/` scratch directory

## Odoo stack baseline

The repository currently describes this local sandbox:

- Odoo image: `odoo:17.0`
- PostgreSQL image: `postgres:15`
- Odoo HTTP port: `8069`
- Odoo longpolling port: `8072`
- PostgreSQL port: `5432`
- Database name: `odoo_research`
- Odoo admin password: `admin`
- Odoo login: `admin`
- Odoo password: `admin`
- PostgreSQL user: `odoo`
- PostgreSQL password: `odoo_pw`
- Mounted addon path: `./custom_addons -> /mnt/extra-addons`
- Odoo config lock: `dbfilter = ^odoo_research$`

Bootstrap and reset entrypoints:

- `./scripts/init.sh`: starts PostgreSQL, initializes core Odoo modules, then starts Odoo
- `./scripts/reset.sh`: destroys the containers and volumes, then rebuilds the stack

## Sandbox data baseline

The sandbox dataset is furnished through `potential_scripts/furnish_database.py` using Odoo JSON-RPC calls rather than raw SQL inserts. The data spec and task design are described in:

- `potential_scripts/database_furnish.md`
- `potential_scripts/task_scenario.md`
- `potential_scripts/database_structure.txt`
- `potential_scripts/expected_data_format.txt`

Key seeded entities in the benchmark sandbox:

- Ambiguous phone catalog entries such as Samsung Galaxy S24, S24 Ultra, and S24 FE
- Near-duplicate accessories such as USB-C cable variants and USB-C chargers
- Duplicate customer names such as two distinct `Tanaka Yuki` customer records
- Existing sales orders, CRM leads, invoices, and stock quantities designed to trigger Halluci-Action error cases
- Inventory states with reserved stock and edge cases used to test over-claim, substitution, fabrication, and constraint violations

Behavior logging baseline:

- Each tool call goes through `research/gateway.py`
- The gateway writes per-action audit records into `halluci_audit`
- The saved trajectory JSON captures assistant text, tool calls, tool results, and extracted claims

## Included experiment artifacts

The repository snapshot intentionally keeps these run files under `research/experiments/runs/`:

- `20260328T104231Z_deepseek_please_process_the_pending_samsung_galaxy_s24_or.json`
- `20260328T104642Z_deepseek_please_process_the_pending_samsung_galaxy_s24_or.json`
- `20260328T111828Z_deepseek_please_process_the_pending_samsung_galaxy_s24_or.json`
- `20260328T112211Z_deepseek_please_process_the_pending_samsung_galaxy_s24_or.json`

Observed metadata in the included runs:

- provider: `deepseek`
- models: `deepseek-chat` and `deepseek-reasoner`
- task family: Samsung Galaxy S24 order processing for Tanaka Yuki
- knowledge level: `KL1`

No API keys or local absolute filesystem paths were found in the retained JSON run artifacts during the publication check.

## End-to-end workflow

From a clean clone, the expected workflow is:

1. Start the Odoo and PostgreSQL services.

```bash
cd odoo-research
./scripts/init.sh
```

2. Create a Python environment and install the research dependencies.

```bash
python3 -m venv research/.venv
source research/.venv/bin/activate
pip install -r research/requirements.txt
```

3. Create a local environment file for API keys and local service settings.

```bash
cp research/.env.example research/.env
```

4. Seed the Odoo sandbox data.

```bash
python3 potential_scripts/furnish_database.py
```

5. Run a benchmark trajectory.

```bash
python3 -m research.harness run \
  --agent deepseek \
  --model deepseek-chat \
  --task-id task1 \
  --kl KL1
```

6. Inspect the saved trajectory output in `research/experiments/runs/`.

7. Optionally post-process the trajectory against `halluci_audit` for action-level analysis.

## Manual push procedure

The user requested a manual push, so no remote push was performed automatically. To publish this prepared directory yourself:

```bash
cd /Volumes/Adeline/NLP_FP/odoo-research

git init
git branch -M main

git config user.name
git config user.email

git remote add origin https://github.com/kaifang1020/Halluci-action.git
git add .
git status
git commit -m "Initial self-contained Halluci-Action Odoo research package"
git push -u origin main
```

If `origin` already exists, replace the `git remote add origin ...` line with:

```bash
git remote set-url origin https://github.com/kaifang1020/Halluci-action.git
```

## Authorship note

This prepared snapshot does not add any co-author trailers or contributor metadata. GitHub authorship will be determined by the local `git` identity you use when creating the commit and pushing it.

## Publication cleanup performed locally

Before handing the repository back for manual push, the following cleanup was applied:

- removed all `._*` AppleDouble files
- removed all Python `__pycache__/` directories
- removed the unused root-level `experiments/` directory
- added `.gitignore` for secrets, caches, virtual environments, and macOS artifacts
- aligned the README files with the actual repository layout and runtime behavior
