# Experiments v1 Layout

This directory stores hidden-audit trajectories.

## Layout

Independent tasks:

```text
independent/<domain>/trajectories/<task_id>_<agent>_<model>.json
independent/<domain>/audits/<task_id>_<agent>_<model>__audit.json
```

Dependent chains:

```text
dependent/<domain>/<chain>/trajectories/<task_id>_<agent>_<model>.json
dependent/<domain>/<chain>/audits/<task_id>_<agent>_<model>__audit.json
```

The main trajectory stores only agent-visible tool results. Full state snapshots
and gateway audit payloads live in the matching audit file.

Each tool result has a stable `action_id` such as `step3_action0`. The matching
audit record uses the same `action_id`, so human notes and judge outputs can
refer to one action without relying on database audit IDs.

## Run Policy

- Independent tasks: reset and furnish the database before every task.
- Dependent chains: reset and furnish once per chain, then run all tasks in the
  chain sequentially so state carries forward inside the chain.

Use:

```bash
research/.venv/bin/python scripts/run_experiments_v1.py --mode independent
research/.venv/bin/python scripts/run_experiments_v1.py --mode dependent
research/.venv/bin/python scripts/run_experiments_v1.py --mode all
```

Useful filters:

```bash
research/.venv/bin/python scripts/run_experiments_v1.py --mode independent --tasks S-1 A-1 D-5
research/.venv/bin/python scripts/run_experiments_v1.py --mode dependent --chains A2_A6 M1_M6
research/.venv/bin/python scripts/run_experiments_v1.py --mode all --dry-run
```

Run summaries are written under `run_summaries/`.
