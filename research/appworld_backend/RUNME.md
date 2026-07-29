# Halluci-Action × AppWorld PoC — RUN ME

Runs the **existing** Halluci-Action hallucination-detection pipeline (reused agents +
claim capture + audit-sidecar schema) on top of an **AppWorld** world, executing every
tool call **in-process** via `world.apis.<app>.<api>(**params)`.
No MCP, no server, no AppWorld code-agent, and we never call `world.evaluate()`.

Files (all under `research/`):

| File | Role |
|------|------|
| `tools/appworld_tools.py` | `AppWorldToolExecutor`: login/token helper, `execute()` dispatch, `build_tool_schemas()` (mirrors `OdooToolExecutor` + `ToolSpec`). |
| `appworld_gateway.py` | `AppWorldGateway`: Postgres-free gateway; in-memory audit + per-tool `state_delta` via SQLite snapshot diff. |
| `run_appworld_poc.py` | Driver: builds the world, tools, reused agent; runs the `harness._run_single` loop; writes trajectory + audit JSON in the **identical** schema. |

---

## 1. Environment (already being set up by another process — do NOT set it up here)

- venv:          `/Users/maokaifang/appworld-root/venv`
- `APPWORLD_ROOT`: `/Users/maokaifang/appworld-root`   (data at `.../data`)

The venv has `appworld` installed. The driver also imports the reused Halluci-Action
harness, which transitively imports a few libraries. Make sure the venv has them:

```bash
/Users/maokaifang/appworld-root/venv/bin/pip install \
    openai anthropic python-dotenv click psycopg2-binary structlog
```

> `psycopg2-binary` is only needed because importing `research.harness` pulls in
> `research.gateway` (the Odoo/Postgres gateway) at module load. **Our** AppWorld
> gateway never touches Postgres — no database needs to be running.

---

## 2. Fill-ins in `research/run_appworld_poc.py` (you MUST complete these)

1. **`TASK_ID`** — currently `"TODO_PASTE_TASK_ID"`. Pick a real task id inside the venv:

   ```bash
   cd /Users/maokaifang/Downloads/Halluci-action-codex-newjudge-complete-20260428-184455_latest
   APPWORLD_ROOT=/Users/maokaifang/appworld-root \
   /Users/maokaifang/appworld-root/venv/bin/python -c \
     "from appworld.task import load_task_ids; print(load_task_ids('train')[:20])"
   ```
   Paste one id (e.g. `"a8f3c1_1"`) into `TASK_ID`.

2. **`EXPOSED_APIS`** — the task-agnostic tool set (marked `user: paste the chosen task's
   required apis here`). Entries are AppWorld function-calling names of the form
   `"<app>__<api>"` (e.g. `"venmo__show_venmo_balance"`, `"gmail__send_email"`). Two
   example entries are provided; **replace them** with the chosen task's required APIs.
   To see a task's ground-truth required APIs / apps, inspect
   `world.task` (`allowed_apps`, and the task's `ground_truth`) or the task's
   `required_apis` in the AppWorld data. Do **not** dump all ~457 APIs.

3. *(optional)* **`TOOL_CONSTRAINTS`** — per-tool constraint strings, surfaced only at
   KL1 (mirrors `ToolSpec.constraints`).

4. **Model / provider / key** — set via env vars (defaults shown):
   - `HALLUCI_PROVIDER=openai` (or `anthropic`)
   - `HALLUCI_MODEL=gpt-4o-mini` (pick one your key can access)
   - `HALLUCI_KL=KL1` (KL1 | KL2 | KL3)
   - API key: `OPENAI_API_KEY` **or** `ANTHROPIC_API_KEY` (resolved by `research.config`).

---

## 3. Run

```bash
cd /Users/maokaifang/Downloads/Halluci-action-codex-newjudge-complete-20260428-184455_latest

APPWORLD_ROOT=/Users/maokaifang/appworld-root \
HALLUCI_PROVIDER=openai \
HALLUCI_MODEL=gpt-4o-mini \
HALLUCI_KL=KL1 \
OPENAI_API_KEY=sk-... \
/Users/maokaifang/appworld-root/venv/bin/python -m research.run_appworld_poc
```

- Run from the **Halluci-Action repo root** (so `research` is importable) with the
  **AppWorld venv** python (so `appworld` is importable).
- Output goes to `research/runs_appworld/{trajectories,audits}/` (override with
  `HALLUCI_RUNS_DIR`). AppWorld's own logs/dbs go under
  `$APPWORLD_ROOT/experiments/outputs/halluci_action_appworld_poc/`.

---

## 4. Judge

The trajectory (`trajectory_v2_hidden_audit`) and audit sidecar (`audit_sidecar_v1`) are
written by the reused `research.harness.split_audit_payload`, so the schema is **identical**
to native Halluci-Action runs. Point the existing stage-1 judge at the two output dirs
(`research/runs_appworld/trajectories` and `.../audits`) exactly as you would for an Odoo
run — no judge changes needed.

---

## 5. Design notes (what's intentionally different from stock AppWorld)

- **In-process, apis-object only.** Actions are `world.apis.<app>.<api>(**params)`. We
  never call `world.execute` for actions, and never `world.evaluate()` (its
  success-based score is discarded; only our hallucination judge matters).
- **Login/token.** `apis.supervisor.show_profile()` + `apis.supervisor.show_account_passwords()`
  need no token in-process; per-app tokens come from `apis.<app>.login(username, password)`
  and are injected automatically only for APIs whose schema declares `access_token`
  (AppWorld runs with `raise_on_extra_parameters=True`).
- **Per-tool `state_delta`.** We snapshot the touched app's live in-memory SQLite DB
  (`save_local_dbs(format="full")` → SQLite `.backup()`) before/after each call and diff
  by-id (INSERT/UPDATE/DELETE), reusing `ToolGateway._compute_delta`'s shape. The tool
  return value is always the primary evidence; if a snapshot fails, `state_delta` degrades
  to a best-effort placeholder (see the `TODO`s in `appworld_gateway.py`).
- **Rewritten system prompt.** Neutral about autonomy; **requires** a one-sentence
  statement before each tool call and a one-sentence restatement after each result (to
  elicit `claim_pre`/`claim_post`). Uses `world.task.datetime` as "now".
- **Return-structure trap.** `venmo__show_venmo_balance` wrapper returns
  `{total, pending, available}` — a multi-field shape the agent may mis-cite (Over-claim).
