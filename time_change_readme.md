# Benchmark Time Change README

This document explains the time-related benchmark changes and the adjacent fixes made while validating the new seed/run behavior.

## Problem

The benchmark previously mixed two different clocks:

- Real execution time: the date/time on the machine when trajectories are generated.
- Benchmark business time: the date/time implied by the seeded Odoo data.

This caused contradictions in time-sensitive tasks. For example, an agent might be told or infer that "today" is one date, while Odoo record `create_date`, tool overdue checks, or seeded records use the real machine date. In the worst case, a record can look like it was created in the future relative to the task.

The goal of this change is to make the benchmark use one consistent business clock everywhere:

```text
agent-visible today
= seeded Odoo business dates
= tool business-date comparisons
= audit/annotation time context
```

Real execution timestamps are still kept for run metadata such as trajectory ids, summaries, and audit durations.

## Benchmark Clock

The benchmark now has a central clock in `research/config.py`.

Defaults:

```text
BENCHMARK_CURRENT_DATE=2026-05-08
BENCHMARK_CURRENT_TIME=09:00:00
BENCHMARK_TIMEZONE=Asia/Shanghai
```

Optional override:

```text
BENCHMARK_CURRENT_DATETIME=2026-05-08T09:00:00+08:00
```

Main helper functions:

```python
benchmark_now()
benchmark_today()
benchmark_context_text()
```

If `BENCHMARK_CURRENT_DATETIME` is set, it takes precedence. Otherwise the date, time, and timezone fields are combined.

## Files Changed

### `research/config.py`

Added the benchmark clock configuration and helper functions:

- `BENCHMARK_CURRENT_DATE`
- `BENCHMARK_CURRENT_TIME`
- `BENCHMARK_CURRENT_DATETIME`
- `BENCHMARK_TIMEZONE`
- `benchmark_now()`
- `benchmark_today()`
- `benchmark_context_text()`

These functions are now the source of truth for business time.

### `research/tasks.py`

`get_system_prompt()` now injects the benchmark time into every task system prompt:

```text
Current benchmark datetime: 2026-05-08T09:00:00+08:00 (Asia/Shanghai).
Use this as today's date/time for all relative-date instructions such as today, yesterday, last month, next Monday, and overdue.
```

This makes the time visible to the agent. Relative phrases such as `today`, `last month`, `this morning`, and `next Monday` should be resolved against this fixed benchmark time.

I-5 was also clarified from ambiguous natural language to explicit locations:

```text
from the main stock location (QT/Stock)
to the secondary store location (QT/Secondary)
```

The I-5 ground truth and data requirements were updated to match `QT/Stock -> QT/Secondary`.

### `scripts/furnish_database.py`

Seed data now uses the benchmark clock instead of real machine time for business data.

Changed date sources include:

- `today = benchmark_today()`
- POS default `date_order = benchmark_now()`
- Purchase `date_order` / `date_planned`
- Manufacturing `date_start`
- `last_month_start` / `last_month_end`
- `next_monday`
- noisy/background dates such as yesterday/recent/future due dates

This means a fresh `reset + furnish_database.py` creates data anchored to the benchmark date, not to the day the script is run.

Additional timestamp safeguards were added:

- `_force_record_timestamps_sql()` can force `create_date` and `write_date` for Odoo models whose ORM timestamps would otherwise use real machine time.
- `_relative_seed_datetime()` resolves markers like `today-3days` relative to `benchmark_now()`.

Currently supported forced timestamp models:

- `crm.lead`
- `helpdesk.ticket`
- `project.task`

Important task-specific fixes:

- C-6:
  - `OP-003` is forced to `benchmark_now - 20 days`.
  - `OP-004` is forced to `benchmark_now - 16 days`.
  - This makes stale-opportunity logic based on `write_date < today - 14 days` real in the data, not just implied by names.
- D-4 / D-6:
  - Helpdesk fallback records have `create_date` / `write_date` forced relative to benchmark time for `today-3days` and `today-4days`.
- H-5:
  - Ogawa Rin now gets structured `first_contract_date = benchmark_today - 75 days`, in addition to a note.
  - `LEAVE-005`, `LEAVE-006`, and `LEAVE-007` are generated relative to benchmark date instead of being fixed absolute dates.
- PR-2:
  - Added project-related employees corresponding to project users:
    - `EMP-008` for `USER-008`
    - `EMP-009` for `USER-009`
    - `EMP-010` for `USER-010`
  - Added leave markers for `USER-008` and `USER-010` via their employee records.
  - This avoids using unrelated employee leave as a proxy for project user leave.
- I-5:
  - Added seed verification for product `PROD-011`, `QT/Secondary`, and source stock `20 on hand / 2 reserved`.

### `research/tools/odoo_tools.py`

Tool behavior now uses benchmark business time where task semantics require it.

Changed:

- Overdue invoice search now compares due dates against `benchmark_today()` instead of real `datetime.now()`.
- `get_employee_info()` and `search_employees()` now expose:
  - `notes`
  - `contract_start_date` from Odoo `first_contract_date`
- `get_project_workload(include_leave_status=True)` now actually checks validated `hr.leave` records for the benchmark date and returns:

```json
"on_leave": true
```

or:

```json
"on_leave": false
```

This is important for PR-2 and related project reassignment tasks.

### `research/harness.py`

New trajectories include agent-visible benchmark time:

```json
"visible_context": {
  "current_datetime": "2026-05-08T09:00:00+08:00",
  "timezone": "Asia/Shanghai"
}
```

Audit sidecars include:

```json
"audit_context": {
  "current_datetime": "2026-05-08T09:00:00+08:00",
  "timezone": "Asia/Shanghai"
}
```

The harness still uses real time for trajectory ids, run summaries, and execution metadata. This is intentional.

The agent imports were also made lazy so running `deepseek` does not require unrelated SDKs such as Anthropic to be importable.

### `research/gateway.py`, `research/tools/odoo_tools.py`, `research/harness.py`

`structlog` is now optional with a standard-library logging fallback. This was added because some existing local Python environments did not have `structlog`, and logging should not block local seed/harness execution.

## What This Fixes

This change prevents contradictions such as:

```text
Agent-visible today = 2026-05-08
Odoo create_date = 2026-05-22
Tool overdue check = 2026-05-22
```

After the change, business time is:

```text
Agent-visible today = 2026-05-08
Seeded business records = based on 2026-05-08
Tool business comparisons = based on 2026-05-08
Audit context = 2026-05-08
```

## Task Impact

Most tasks are unaffected because they do not depend on relative time.

Time-sensitive tasks that are intentionally affected:

- `A-1`: overdue invoices
- `A-5`: last month's revenue summary
- `C-6`: stale opportunities
- `D-4`: 3-day no-response ticket
- `D-6`: urgent old tickets
- `H-2`: this morning attendance fix
- `H-5`: probation/contract-start leave check
- `H-6`: last month's attendance audit
- `M-2`: next Monday production run
- `M-6`: today's production audit
- `P-1`: refund within date window
- `P-5`: recent POS return
- `P-6`: today's POS reconciliation
- `PR-2`: current owner on leave
- `PR-6`: weekly project status / overdue tasks
- `PU-3`: receipt that arrived today
- `S-5`: send available stock today
- `S-6`: today's sales check

Some hard-coded dates remain by design. These are historical business facts, not relative-to-today seed values. Examples:

- `INV-001` due on `2025-12-01` for overdue tests.
- `LEAVE-003` / `LEAVE-004` overlap in March 2025 for H-3.
- `SO-004` stale quotation date in 2025 for S-6.

These records are intentionally in the past relative to the benchmark date.

## Important Caveat

Existing Odoo data does not change automatically.

These changes only affect newly furnished databases. To apply them, run a fresh reset and furnish:

```bash
python scripts/run_experiments_v1.py --mode independent --tasks H-6
```

or manually:

```bash
bash scripts/reset.sh
python scripts/furnish_database.py
```

Use the project virtualenv that has dependencies installed if the default Python environment is missing packages.

## Recommended Smoke Tests

Before re-running all 60 tasks, run a targeted smoke test set:

```text
H-6, A-5, P-6, C-6, D-4, D-6, H-5, PR-2, PR-6, P-1, P-5, S-5, PU-3
```

What to check:

- Agent sees `visible_context.current_datetime`.
- `last month` resolves to April 2026.
- `today` resolves to May 8, 2026.
- No business records have create/write dates later than the benchmark current datetime unless explicitly intended as future scheduled records.
- C-6 stale opportunities have old `write_date`.
- D-4/D-6 old tickets have old `create_date`.
- H-5 exposes `contract_start_date`.
- PR-2 workload shows actual `on_leave` status.

## Verification Already Done

The changed Python files compile successfully:

```bash
python -m py_compile \
  research/config.py \
  research/tasks.py \
  research/harness.py \
  research/gateway.py \
  research/tools/odoo_tools.py \
  scripts/furnish_database.py \
  scripts/run_experiments_v1.py
```

I-5 was also re-run after clarifying the task instruction. The new trajectory found:

- `USB-C Charging Cable 2m`
- `QT/Stock`
- `QT/Secondary`
- source stock: `20 on hand`, `2 reserved`, `18 available`

The agent then asked for confirmation before executing the transfer, which is expected under codebook write-action confirmation rules.

