# Halluci-Action Odoo Research Stack

This directory is a self-contained Odoo 17 + PostgreSQL 15 research sandbox plus the Halluci-Action experiment harness. It is being consolidated as the main repository for the expanded task benchmark.

## Repository layout

- `docker-compose.yml`: local Odoo 17 and PostgreSQL 15 services.
- `odoo.conf`: Odoo configuration pinned to the `odoo_research` database.
- `scripts/init.sh`: bootstrap the database and start the stack.
- `scripts/reset.sh`: rebuild the environment from scratch.
- `scripts/furnish_database.py`: canonical database seeder for benchmark records.
- `potential_scripts/`: older compatibility wrappers, task specs, and design notes.
- `research/`: Python package for agent adapters, tool registry, gateway, task registry, harness, and post-processing.
- `research/tasks.py`: canonical reusable task registry. Runners discover task IDs from `TASKS`.
- `research/experiments/runs/`: trajectory JSON outputs included in this snapshot.
- `docs/`: analysis notes and publishing log.
- `custom_addons/`: optional local Odoo addons mounted into `/mnt/extra-addons`.

## Quick start

```bash
cd /gpfsnyu/scratch/km6704/Agent/Halluci-action/Halluci-action-codex-expanded-seed-data-guide
./scripts/init.sh

python3 -m venv research/.venv
source research/.venv/bin/activate
pip install -r research/requirements.txt

cp research/.env.example research/.env
python3 scripts/furnish_database.py

./run_experiment.sh list
./run_experiment.sh S-1
```

Then open `http://localhost:8069`.

## Default credentials

- Database: `odoo_research`
- Master password: `admin`
- Login: `admin`
- Password: `admin`

## Reset

```bash
cd /gpfsnyu/scratch/km6704/Agent/Halluci-action/Halluci-action-codex-expanded-seed-data-guide
./scripts/reset.sh
python3 scripts/furnish_database.py
```

## Tasks

Tasks are not listed manually here.  They are defined in `research/tasks.py` and
discovered dynamically by the runner, so adding a task to `TASKS` makes it
available to the CLI.

```bash
./run_experiment.sh list
DOMAIN=sales ./run_experiment.sh list
DOMAIN=inventory DIFFICULTY=medium ./run_experiment.sh list
python3 -m research.tasks
```

## What is intentionally tracked

- The full `research/` package, including `research/experiments/runs/`.
- The Odoo stack definition and benchmark seeding scripts under `scripts/`.
- Compatibility scripts and design notes under `potential_scripts/`.
- Repository documentation for setup, experiments, and publishing.

## What is intentionally ignored

- Local secrets such as `.env`.
- Virtual environments, Python caches, and macOS resource fork files.
- The unused top-level `experiments/` scratch directory.

## Notes

- PostgreSQL is exposed on `localhost:5432` for direct inspection.
- `custom_addons/` is mounted into the container at `/mnt/extra-addons`.
- `dbfilter = ^odoo_research$` keeps the instance pinned to one database.
- The detailed publish log is in `docs/GITHUB_PUSH_LOG_2026-03-28.md`.
