# Halluci-Action Odoo Research Stack

This directory is a self-contained Odoo 17 + PostgreSQL 15 research sandbox plus the Halluci-Action experiment harness. If you publish it to GitHub, this `odoo-research/` directory should be the repository root.

## Repository layout

- `docker-compose.yml`: local Odoo 17 and PostgreSQL 15 services.
- `odoo.conf`: Odoo configuration pinned to the `odoo_research` database.
- `scripts/init.sh`: bootstrap the database and start the stack.
- `scripts/reset.sh`: rebuild the environment from scratch.
- `potential_scripts/`: sandbox seeding scripts, task specs, and design notes.
- `research/`: Python package for agent adapters, tool registry, gateway, harness, and post-processing.
- `research/experiments/runs/`: trajectory JSON outputs included in this snapshot.
- `docs/`: analysis notes and publishing log.
- `custom_addons/`: optional local Odoo addons mounted into `/mnt/extra-addons`.

## Quick start

```bash
cd odoo-research
./scripts/init.sh

python3 -m venv research/.venv
source research/.venv/bin/activate
pip install -r research/requirements.txt

cp research/.env.example research/.env
python3 potential_scripts/furnish_database.py

./run_experiment.sh task1
```

Then open `http://localhost:8069`.

## Default credentials

- Database: `odoo_research`
- Master password: `admin`
- Login: `admin`
- Password: `admin`

## Reset

```bash
cd odoo-research
./scripts/reset.sh
python3 potential_scripts/furnish_database.py
```

## What is intentionally tracked

- The full `research/` package, including `research/experiments/runs/`.
- The Odoo stack definition and sandbox seeding scripts under `potential_scripts/`.
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
