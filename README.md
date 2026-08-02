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

## Two runtime paths

This stack supports two completely separate runtimes for the Odoo + Postgres
backend. Pick the one matching where you're running and stick with it; the
env var `HALLUCI_RUNTIME` controls which reset/init scripts the batch runners
will invoke.

### 1. Local Docker (default)

Use when you have docker access. `scripts/init.sh` / `scripts/reset.sh` manage
containers via `docker-compose.yml`.

```bash
export HALLUCI_RUNTIME=docker        # default if unset
./scripts/init.sh
python3 scripts/furnish_database.py
./run_experiment.sh S-1
```

### 2. HPC (no docker)

Use on HPC nodes where docker is not available. Odoo and PostgreSQL run as
user processes from the `odoo-research` conda env; `scripts/init_hpc.sh` and
`scripts/reset_hpc.sh` manage them.

Prerequisites:

- conda env `odoo-research` with `odoo`, `pg_ctl`, `psql`, `initdb` installed
- writable `DATA_ROOT` — default is `/gpfsnyu/scratch/km6704/odoo-research`,
  **override per-user** via `export DATA_ROOT=/gpfsnyu/scratch/$USER/odoo-research`
- no other process holding port 5432 / 8069 on the node

```bash
export HALLUCI_RUNTIME=hpc
export DATA_ROOT=/gpfsnyu/scratch/$USER/odoo-research
bash scripts/init_hpc.sh
conda run -n odoo-research python scripts/furnish_database.py
./run_experiment.sh S-1
./run_experiment_v2.sh        # full multi-agent benchmark sweep (see below)
```

### Runtime awareness in batch scripts

| Script | Runtime aware? |
|---|---|
| `scripts/run_experiments_v1.py` | yes, via `HALLUCI_RUNTIME` |
| `scripts/run_dependent_remaining_chains.sh` | yes |
| `run_experiment_v2.sh` | yes; defaults to `hpc` |
| `run_batch_independent.sh` | docker-only (legacy) |

## Sweep configuration (v2 benchmark)

`run_experiment_v2.sh` iterates over `(agent, model, kl)` combinations defined
in YAML, so adding an agent does not require editing the shell script.

- Config file: `experiments/sweeps/v2.yaml`
- Reader: `scripts/sweep_pairs.py` (emits TSV the shell loops over)
- Aggregator: `scripts/summarize_sweep.py` (writes
  `logs/sweep_summary_<ts>.md` comparing per-task success/failure/runtime
  across pairs)

To run with a different sweep file:

```bash
SWEEP_CONFIG=experiments/sweeps/quick.yaml ./run_experiment_v2.sh
```

Resume after an interruption with `SKIP_EXISTING=1 ./run_experiment_v2.sh`.
**Caveat:** if a *dependent chain* was interrupted mid-run, `--skip-existing`
will skip the already-written tasks but the chain head will not be re-reset,
leaving the tail to run against a dirty DB. Manually delete the trajectories
of any half-finished chain under
`research/experiments_v1/dependent/<domain>/<chain>/trajectories/` before
resuming.

## Benchmark clock (time-change)

All business-time logic (agent system prompt, tool overdue/leave checks, seed
dates, audit context) reads a central benchmark clock from
`research/config.py`, configured via env vars (defaults shown):

| Var | Default |
|---|---|
| `BENCHMARK_CURRENT_DATE` | `2026-05-08` |
| `BENCHMARK_CURRENT_TIME` | `09:00:00` |
| `BENCHMARK_TIMEZONE` | `Asia/Shanghai` |
| `BENCHMARK_CURRENT_DATETIME` | *(unset; overrides date+time when set)* |

`run_experiment_v2.sh` exports these defaults; override by setting them in
`research/.env` or by prefixing the command. Full design notes in
`time_change_explanation_zh.md` and `time_change_readme.md`.

## Configuration reference

Knobs split across argparse (per-invocation) and env vars (cross-process
constants like connections and the benchmark clock).

| Knob | Layer | Default | Defined in | Purpose |
|---|---|---|---|---|
| `--mode` | argparse | `all` | `scripts/run_experiments_v1.py:64` | `independent` / `dependent` / `all` |
| `--tasks` | argparse | all | `:65` | Limit to specific independent task IDs |
| `--chains` | argparse | all | `:66` | Limit to specific dependent chain names |
| `--agent` | argparse | `$DEFAULT_AGENT` or `deepseek` | `:67` | Provider |
| `--model` | argparse | `$DEFAULT_MODEL` or `deepseek-chat` | `:68` | Model name |
| `--kl` | argparse | `$KL` or `KL1` | `:69` | Knowledge-level prompt |
| `--max-steps` | argparse | `$MAX_STEPS` or `15` | `:70` | Max agent steps per task |
| `--timeout-sec` | argparse | `300` | `:71` | Per-task timeout |
| `--runs` | argparse | `1` | `:72` | Repeats per task |
| `--no-codebook` | argparse | off | `:73` | Disable shared codebook |
| `--no-reset` | argparse | off | `:74` | Skip reset/furnish (debug only) |
| `--skip-existing` | argparse | off | `:75` | Skip when matching trajectory exists |
| `--dry-run` | argparse | off | `:76` | Print plan only |
| `HALLUCI_RUNTIME` | env | `docker` | `run_experiments_v1.py` + `run_dependent_remaining_chains.sh` | `docker` or `hpc` |
| `BENCHMARK_CURRENT_DATE` | env | `2026-05-08` | `research/config.py:38` | Benchmark date |
| `BENCHMARK_CURRENT_TIME` | env | `09:00:00` | `:39` | Benchmark time |
| `BENCHMARK_CURRENT_DATETIME` | env | *empty* | `:40` | Full ISO datetime override |
| `BENCHMARK_TIMEZONE` | env | `Asia/Shanghai` | `:41` | Timezone |
| `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD` | env | localhost:8069, odoo_research, admin, admin | `:95-98` | Odoo HTTP |
| `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` | env | localhost, 5432, odoo_research, odoo, odoo_pw | `:103-107` | Postgres direct |
| `DATA_ROOT` | env | `/gpfsnyu/scratch/km6704/odoo-research` | `scripts/init_hpc.sh:14` / `scripts/reset_hpc.sh:10` | HPC persistent root (**override per user**) |
| `PG_PORT`, `ODOO_HTTP_PORT` | env | 5432, 8069 | `scripts/init_hpc.sh:11-12` | HPC ports |
| `CONDA_ENV_NAME` | env | `odoo-research` | `scripts/init_hpc.sh:7` | conda env |
| `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` / `DASHSCOPE_API_KEY` / `MOONSHOT_API_KEY` | env | *unset* | `research/config.py:18-25` | Provider credentials |
| `RUNS`, `MAX_STEPS`, `KL` | env | `1`, `15`, `KL1` | `run_experiment_v2.sh` | Sweep defaults |
| `SKIP_EXISTING`, `DRY_RUN` | env | `0`, `0` | `run_experiment_v2.sh` | Sweep flags |
| `SWEEP_CONFIG` | env | `experiments/sweeps/v2.yaml` | `run_experiment_v2.sh` | Swap sweep file |

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
