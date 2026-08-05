# AppWorld run status and how to reproduce it

Snapshot date: **2026-07-30**. Repo: `Halluci-action-codex-newjudge-complete-20260428-184455_latest`,
branch `codex/newjudge-complete-20260428-184455`, HEAD `21a46fce`.

This document has one job: let two people run the **same** pipeline on **different** tasks so the
results can be pooled into one table. Everything below was verified against the files in
`research/appworld_backend/` on the snapshot date by counting real artifacts — nothing is estimated
unless explicitly labelled.

Reading order if you are new: section 3 (environment) -> section 6 (verify you are in sync) ->
section 5 (who does what) -> section 4 (commands).

---

## 0. Who is running what — read this before claiming any task

The task lists live in the repo, not in this document, so they cannot drift from what is
actually being run:

| File (`research/appworld_backend/tasks/`) | Contents |
|---|---|
| `batch_A_baseline_100.json` | 100 tasks — the original baseline. **Claimed, in progress.** |
| `batch_B_expansion_55.json` | 55 tasks — expansion, one variant per template, difficulty-balanced. **Claimed, in progress.** |
| `claimed_all.json` | The union, 155 tasks. **Do not start these; they are already running.** |
| `available_pool.json` | 151 tasks nobody has claimed — one variant per template, so no two entries are the same task with a different name. **Pick from here.** |

To see what is actually finished right now, do not read the snapshot below — run:

```bash
cd /path/to/repo
APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
  /Users/maokaifang/appworld-root/venv/bin/python research/appworld_backend/status.py
```

It counts artifacts on disk (trajectories and `pipeline_*.html`) and reports both batches plus
the unclaimed pool. It also emits paste-ready task lists:

```bash
# tasks still missing a trajectory
... status.py --todo trajectories

# tasks with a trajectory but no judge output
... status.py --todo judge
```

**Claiming work.** Take a slice of `available_pool.json`, write it to a new
`tasks/batch_C_<yourname>.json`, and commit that file before you start. The point is that the
claim is visible in git, so the same task never gets run twice. Split by task, never by model —
a task judged with three of the five models is not comparable with one judged with all five.

Note that `available_pool.json` holds one variant per template on purpose. AppWorld ids sharing
a prefix (`0d8a4ee_1`, `_2`, `_3`) are the same task with the names swapped, so running all three
costs 3x and buys very little. If you want more volume, prefer more templates over more variants.

Before running anything, confirm your inputs match — see
[section 6](#6-verifying-you-are-in-sync). A different `codebook.md` silently changes the policy
axis, and results scored against different codebooks cannot be pooled.

## 0b. Batch C — the remaining templates, split two ways

`claimed_all.json` (155 tasks) is batch A + B and is already running. Batch C covers everything
left, and is the work to divide:

| File | Tasks | Owner |
|---|---|---|
| `tasks/batch_C_you.json` | 112 | the original runner |
| `tasks/batch_C_teammate.json` | 111 | the collaborator |

**Why 223 tasks and not 577.** 577 AppWorld tasks remain unclaimed, but they are only 223
distinct templates — ids sharing a prefix (`0d8a4ee_1/_2/_3`) are one task with the names
swapped, and measured HAR across such variants is nearly identical. Batch C therefore takes one
variant per template: full coverage of every task type for 40% of the compute. Running all 577
costs 2885 cells; 223 templates costs 1115.

The two halves were interleaved after sorting by difficulty and primary app, so they match
closely: difficulty 30/40/42 versus 30/40/41, and comparable app mixes. Either half is
independently analysable if the other stalls.

### Before you split: check whether a second key actually adds throughput

This is unresolved and it decides whether splitting is worth doing at all.

Measured on this machine: raising one judge process from 4 to 6 workers made per-cell latency
jump from 297s to 2018s — nearly 7x — for no throughput gain. Concurrency on a **single key** is
saturated at about 4 workers. What is *not* known is whether a **different** key gets its own
quota, or whether the NYU gateway caps total capacity across keys. If it is the latter, a second
runner buys nothing and simply halves everyone's speed.

Twenty minutes settles it. While the first runner is judging normally:

```bash
# On the teammate's machine, with THEIR key in research/.env — judge just a few cells
APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
  /Users/maokaifang/appworld-root/venv/bin/python research/appworld_backend/judge_all.py \
  --tasks "$(python -c "import json;print(','.join(json.load(open('research/appworld_backend/tasks/batch_C_teammate.json'))[:4]))")" \
  --workers 4 --judge gemini-pro --timeout 1800
```

Then compare the **first runner's** per-cell times before and during that window:

```bash
grep -oE 'HAR=[0-9.]+ .*\(([0-9.]+)s\)' <judge log> | grep -oE '\(([0-9.]+)s\)' | tail -20
```

- Times roughly unchanged -> the keys have separate quota. Split the work; expect close to 2x.
- Times climb noticeably -> capacity is shared. Do **not** split judging: have one person judge
  while the other generates trajectories, which hit the agent providers instead and do not
  contend.

Record the outcome here so nobody re-litigates it.

## 1. Status snapshot

> This is a **snapshot and it goes stale the moment anyone runs anything.** Do not trust these
> numbers after work has happened — re-derive them with `status.py` (section 0) or the counting
> script in [section 1.4](#14-re-derive-these-numbers-yourself). The numbers are a planning aid,
> not a source of truth; the files on disk are the source of truth.

**Design of the run:** the baseline is 100 AppWorld tasks x 5 agent models = **500 cells**; a
55-task expansion (batch B) brings the claimed total to 155 tasks / **775 cells**. A *cell* is
one `(task_id, model)` pair. Stage 1 produces its trajectory; stage 2 judges it.

> **The tables further down in this section describe batch A at 355 trajectories / 281 judged**
> and are kept only as a record of that point. Use the block below, or better, run `status.py`.

### Live counts (regenerated 2026-08-06)

Three batches across two machines. The two halves of batch C do not overlap.

| batch | tasks | trajectories | judged | all-5-models judged |
|---|---|---|---|---|
| A + B (runner 1) | 155 | 771 / 775 | **758 / 775** (97.8%) | 140 |
| C — runner 1's half | 112 | 547 / 560 | **547 / 560** (97.7%) | 100 |
| C — collaborator's half | 111 | 466 / 555 | **146 / 555** (26.3%) | 22 |
| **total** | **378** | | **1451 / 1890** (76.8%) | **262** |

**262 tasks have all five models judged.** Partial tasks must not be mixed into a cross-model
comparison — a task scored on three models is not comparable with one scored on five.

Runner 1's half of batch C is judged out: every cell that has a trajectory has been scored.
The 13 outstanding cells never produced a trajectory in the first place — 9 hit
`Error 400 Access denied` from the qwen provider (which had previously completed 100/100, so
this looks like an account-side change rather than a code fault) and 4 failed because the
agent emitted tool arguments that were not valid JSON.

`tasks/completed_cells.json` carries the exact `(task -> models)` mapping behind these numbers and
is committed on every progress push, so a collaborator can diff it against their own plan without
pulling the multi-hundred-MB `runs/` tree. Regenerate it with:

```bash
APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
  /Users/maokaifang/appworld-root/venv/bin/python research/appworld_backend/status.py --emit
```

The five agent models and their filesystem tags are defined in `judge_all.py` (`MODEL_TAG`) and
`gen_trajectories.py` (`MODELS`):

| provider | model id (use with `gen_trajectories.py --models`) | tag (use with `judge_all.py --models`) |
|---|---|---|
| `deepseek` | `deepseek-chat` | `ds_chat` |
| `deepseek` | `deepseek-reasoner` | `ds_reasoner` |
| `qwen` | `qwen3-8b` | `qwen8b` |
| `gemini` | `@vertexai-hs3645/gemini-3-flash-preview` | `gemflash` |
| `openai` | `gpt-4o-mini` | `gpt4omini` |

### 1.1 Overall

| quantity | count | of 500 |
|---|---|---|
| Stage-1 cells complete (trajectory on disk) | **355** | 71.0 % |
| Stage-2 cells complete (`pipeline_<task>_<tag>.html` on disk) | **281** | 56.2 % |
| Cells **ready to judge now** (trajectory exists, no judged HTML) | **74** | 14.8 % |
| Cells **still needing a trajectory** | **145** | 29.0 % |
| Tasks with all 5 trajectories | **27** | of 100 |
| Tasks with all 5 cells judged | **24** | of 100 |

`runs/judge_summary.jsonl` has exactly **281** rows with **0** duplicate `(task, tag)` keys, which
matches the 281 judged HTMLs — the summary and the artifacts agree.

### 1.2 Per model

| tag | trajectories (of 100) | judged (of 100) | ready to judge | needs trajectory |
|---|---|---|---|---|
| `ds_chat` | 28 | 26 | 2 | 72 |
| `ds_reasoner` | 27 | 27 | 0 | 73 |
| `qwen8b` | 100 | 77 | 23 | 0 |
| `gemflash` | 100 | 77 | 23 | 0 |
| `gpt4omini` | 100 | 74 | 26 | 0 |
| **total** | **355** | **281** | **74** | **145** |

Read this table before planning anything. The shape of the remaining work is:

- The three cheap models (`qwen8b`, `gemflash`, `gpt4omini`) have **all 100 trajectories done**.
  Their only outstanding work is judging (72 cells).
- The two DeepSeek models are the gap: **73 tasks** are missing `ds_chat` and/or `ds_reasoner`
  trajectories (72 missing `ds_chat`, 73 missing `ds_reasoner`; 145 cells total). One task
  (`692c77d_1`) has 4 of 5 — it is missing only `ds_reasoner`.
- Total remaining judge work once trajectories exist: **74 + 145 = 219 cells**.

Distribution of trajectories per task: 27 tasks have 5, 1 task has 4, 72 tasks have 3.
Distribution of judged cells per task: 24 tasks have 5, 4 have 4, 44 have 3, 6 have 2, 1 has 1.

### 1.3 What is on disk in `runs/` (top level, snapshot date)

| glob | files | note |
|---|---|---|
| `pipeline_*.html` | 287 | 281 map to a live cell; 6 are dev-era files with ad-hoc tags (see below) |
| `stage1_*.json` | 296 | more than 281 because some tasks were judged under old tags |
| `stage2_*_{preproc,verdicts}.jsonl` | 601 | 2 per cell + dev-era leftovers |
| `ac_*_{gt,cb}.jsonl` | 577 | 2 per cell + dev-era leftovers |
| `req_*_gt.jsonl` | 284 | 1 per cell + dev-era leftovers |
| `judge_summary.jsonl` | 281 rows | append-only |

The six dev-era HTMLs to ignore: `pipeline_2e9b91e_1`, `pipeline_2e9b91e_1_e2e`,
`pipeline_2e9b91e_1_r02_FIXED`, `pipeline_2e9b91e_1_r02_v2`, `pipeline_2e9b91e_1_r02pipe`,
`pipeline_2e9b91e_2_demo`. They use hand-made tags, not `MODEL_TAG` tags, so `judge_all.py` does not
see them as "done" and no analysis script keyed on the tag will pick them up.

Trajectory files: 399 JSON files under `runs/trajectories/`, of which **32 are archived and must be
excluded** — 29 in `_archive_auth_bug/` and 3 in `_archive_early_poc/`. Both `gen_trajectories.py`
and `judge_all.py` skip any path containing `_archive`. One further file in `_misc/` has
`model: "fixture"` and is likewise ignored (it is not in `MODEL_TAG`). Two cells have repeat runs
left over from development (`024c982_1/ds_chat` has 2 files, `2e9b91e_1/ds_chat` has 4);
`judge_all.py` deduplicates to the newest by mtime, so they count as one cell each.

Seven trajectory cells exist for **six tasks that are not in the 100-task list**
(`024c982_3`, `2d9f728_1`, `2e9b91e_2`, `2e9b91e_3`, `66b7899_2`, `66b7899_3`). None of them are
judged. **Leave them alone** — judging them would add cells that are not part of the 100-task design
and would have to be filtered out of any pooled analysis.

`research/appworld_backend/runs/` is **tracked in git and currently clean** (3165 tracked files;
the only modified file in the whole directory is `tool_exposure.py`, which someone else is editing).
That is what makes merging trivial (section 5.5).

### 1.4 Re-derive these numbers yourself

Copy-pasteable, read-only, takes a few seconds:

```bash
cd /Users/maokaifang/Downloads/Halluci-action-codex-newjudge-complete-20260428-184455_latest
python3 - <<'PY'
import glob, json, os
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path("research/appworld_backend").resolve()
RUNS = BASE / "runs"
TASKS = json.loads((BASE / "tasks_final.json").read_text())   # see section 1.5
MODEL_TAG = {
    "deepseek-chat": "ds_chat",
    "deepseek-reasoner": "ds_reasoner",
    "qwen3-8b": "qwen8b",
    "@vertexai-hs3645/gemini-3-flash-preview": "gemflash",
    "gpt-4o-mini": "gpt4omini",
}
F = set(TASKS)

best = {}
for f in sorted(glob.glob(str(RUNS / "trajectories" / "**" / "*.json"), recursive=True)):
    if "_archive" in f:
        continue
    try:
        tj = json.loads(Path(f).read_text())
    except Exception:
        continue
    t, m = tj.get("task_id"), tj.get("model")
    if not t or m not in MODEL_TAG:
        continue
    k = (t, MODEL_TAG[m])
    if k not in best or os.path.getmtime(f) > os.path.getmtime(best[k]):
        best[k] = f

cells  = {k for k in best if k[0] in F}
judged = {k for k in cells if (RUNS / f"pipeline_{k[0]}_{k[1]}.html").exists()}
per = defaultdict(set)
for t, tag in cells:
    per[t].add(tag)

print(f"tasks in list          : {len(F)}")
print(f"stage-1 cells done     : {len(cells)} / {5*len(F)}")
print(f"stage-2 cells judged   : {len(judged)} / {5*len(F)}")
print(f"ready to judge         : {len(cells) - len(judged)}")
print(f"needs a trajectory     : {5*len(F) - len(cells)}")
print(f"tasks with all 5 trajs : {sum(1 for v in per.values() if len(v) == 5)}")
print()
for tag in MODEL_TAG.values():
    tr = sum(1 for c in cells if c[1] == tag)
    ju = sum(1 for c in judged if c[1] == tag)
    print(f"  {tag:12s} traj={tr:3d}  judged={ju:3d}  ready={tr-ju:3d}  no-traj={len(F)-tr:3d}")
print()
print("tasks missing ds_chat    :", sum(1 for t in F if "ds_chat" not in per[t]))
print("tasks missing ds_reasoner:", sum(1 for t in F if "ds_reasoner" not in per[t]))
PY
```

If `research/appworld_backend/tasks_final.json` does not exist yet, create it from section 1.5
first — that is the one file the whole plan depends on and it is not in the repo as of the snapshot.

### 1.5 The 100-task list (commit this into the repo)

As of the snapshot date this list lived only in a scratchpad directory that gets cleaned. **It must
be committed** to `research/appworld_backend/tasks_final.json` so both collaborators load an
identical list. Write it with:

```bash
cd /Users/maokaifang/Downloads/Halluci-action-codex-newjudge-complete-20260428-184455_latest
cat > research/appworld_backend/tasks_final.json <<'JSON'
[
"024c982_1", "024c982_2", "07bb666_1", "099174d_1", "09ac073_1",
"0d8a4ee_1", "0d8a4ee_2", "0d8a4ee_3", "229360a_1", "229360a_2",
"22cc237_1", "22cc237_2", "22cc237_3", "23cf851_1", "23cf851_2",
"29caf6f_1", "29caf6f_2", "2a163ab_1", "2a163ab_2", "2a163ab_3",
"2e9b91e_1", "32616b5_1", "32616b5_2", "32616b5_3", "34d9492_1",
"34d9492_2", "37a8675_1", "37a8675_2", "383cbac_1", "383cbac_2",
"3aa1a22_1", "3aa1a22_2", "3aa1a22_3", "3ab5b8b_1", "3c13f5a_1",
"3c13f5a_2", "3c13f5a_3", "4fab96f_1", "4fab96f_2", "4fab96f_3",
"530b157_1", "530b157_2", "530b157_3", "57c3486_1", "57c3486_3",
"60d0b5b_1", "60d0b5b_2", "6104387_1", "6104387_2", "6104387_3",
"6171bbc_2", "6171bbc_3", "66b7899_1", "68ee2c9_1", "68ee2c9_3",
"692c77d_1", "692c77d_3", "6c2c621_1", "6c2c621_2", "6c2c621_3",
"6ea6792_1", "6ea6792_2", "6ea6792_3", "76f2c72_1", "76f2c72_2",
"771d8fc_1", "771d8fc_3", "7d7fbf6_1", "7d7fbf6_2", "83a7951_1",
"83a7951_2", "8ce6779_1", "8ce6779_2", "92fe421_1", "986aa4e_1",
"986aa4e_2", "aa8502b_1", "afc0fce_1", "afc0fce_2", "afc0fce_3",
"b0a8eae_1", "b0a8eae_2", "b0a8eae_3", "b7a9ee9_1", "b7a9ee9_2",
"bde252e_1", "bde252e_2", "ce359b5_2", "ce359b5_3", "cf6abd2_1",
"cf6abd2_2", "d0b1f43_1", "d0b1f43_2", "d4e9306_2", "d4e9306_3",
"df61dc5_1", "df61dc5_2", "df61dc5_3", "e3d6c94_1", "e3d6c94_2"
]
JSON
python3 -c "import json;d=json.load(open('research/appworld_backend/tasks_final.json'));print(len(d),'tasks;',len(set(d)),'unique;',len({t.rsplit('_',1)[0] for t in d}),'templates')"
# expect: 100 tasks; 100 unique; 47 templates
```

Note: the built-in `TASKS` list inside `gen_trajectories.py` is a **12-task development list**, not
this one. Always pass `--tasks` explicitly.

### 1.6 Where the 100 sit in the AppWorld task pool

Verified with `appworld.task.load_task_ids(split)` (appworld 0.1.3.post1, python 3.12.5):

| split | tasks in pool | templates in pool | of our 100 | templates used |
|---|---|---|---|---|
| `train` | 90 | 30 | 48 | 21 |
| `dev` | 57 | 19 | 30 | 13 |
| `test_normal` | 168 | 56 | 16 | 7 |
| `test_challenge` | 417 | 139 | 6 | 6 |
| **total** | **732** | **244** | **100** | **47** |

All 100 ids resolve to a split; none are orphans.

**Templates matter for planning.** A task id is `<template>_<variant>`, e.g. `0d8a4ee_1`,
`0d8a4ee_2`, `0d8a4ee_3` are three variants of one template — same instruction pattern, different
data. Our 100 tasks cover only **47 of 244 templates**, and the average of 2.1 variants per template
means the 100 cells are *not* 100 independent observations. If you extend the run, prefer adding
**new templates** over adding variants of templates already covered; variants inflate n without
adding scenario diversity.

Remaining pool if you ever want to extend: **632 tasks / 197 templates untouched**, most of it in
`test_challenge` (417 tasks, 139 templates, of which only 6 templates are used).

---

## 2. What the pipeline produces

Stage 1 (`gen_trajectories.py`) and stage 2 (`judge_all.py`) are two separate batch runners.
Stage 2 shells out to `run_pipeline.py` once per cell, which runs 8 numbered stages. Because every
stage writes a file named after `<task>` and `<tag>`, you can tell exactly how far a cell got by
looking at which files exist.

### 2.1 What a trajectory contains (stage 1 output)

`runner.py` subclasses the real Halluci-Action `ExperimentRunner`, so the schema is identical to a
native (Odoo) run — only the backend gateway is swapped for `AppWorldGateway`, and tool schemas are
injected at runtime from `tools.py::AppWorldToolExecutor.build_tool_schemas()`. Actions execute
in-process as `world.apis.<app>.<api>(**params)`; `world.evaluate()` is **never** called.

Two files per cell, in the schemas `trajectory_v2_hidden_audit` and `audit_sidecar_v1`:

- `runs/trajectories/<MODEL_DIR>/<TASK-UPPER>_<provider>_<model>.json` — keys `schema_version`,
  `trajectory_id`, `task_id`, `task` (the instruction), `agent` (provider), `model`,
  `knowledge_level`, `visible_context` (AppWorld's per-task datetime, corrected by
  `runner._save_result`), `visibility_condition`, `audit_file`, and `steps`. Each step has
  `step_id`, `assistant_text`, `tool_calls`, `tool_results`.
- `runs/audits/<...>__audit.json` — the hidden sidecar: `audit_context`, `source_trajectory`, and
  `records` (the per-step audit rows, including each tool call's `state_delta` computed by
  `gateway.py` via a before/after SQLite snapshot diff).

`task_id` and `model` inside the trajectory JSON — not the filename — are what `judge_all.py` keys
on, which is why the counting script in section 1.4 parses the JSON.

The exposed tool set is chosen per task by `tool_exposure.exposed_apis_for_task(task)`
(involved-app cores + semantic cross-app distractors at ratio 1/3), and `codebook.md` is injected
verbatim into the system prompt (`use_codebook=True`). Neither is hand-listed.

### 2.2 The 8 stages of `run_pipeline.py` and their artifacts

All paths are relative to `research/appworld_backend/runs/`. `<T>` = task id, `<G>` = model tag.

| # | stage | what it does | artifact written |
|---|---|---|---|
| 1 | AGENT | Runs the agent, or with `--traj <path>` **reuses an existing trajectory and skips the agent entirely**. This is how `judge_all.py` always invokes it. | (none new when `--traj` is used) |
| 2 | STAGE1 claim2action | `eval_v3-1_claim2action/stage1/judge.py` extracts the agent's claims from the trajectory. | `stage1_<T>_<G>.json` |
| 3 | STAGE2 fidelity | `eval_v3-1_claim2action/stage2` preprocess (`routing_version="v2"`) then judge, with `stage2_guideline_appworld.md` baked in. Verdicts are `supported` / `not_supported` / `needs_broader_context`; C2A precision = supported / total. | `stage2_<T>_<G>_preproc.jsonl` then `stage2_<T>_<G>_verdicts.jsonl` |
| 4 | ACTION answer-key | `run_action_centric.py --ground-truth` — the WHAT axis: for each action, `said` and its requirement status, scored against the AppWorld answer key. | `ac_<T>_<G>_gt.jsonl` |
| 5 | ACTION codebook | `run_action_centric.py --codebook codebook.md` — the separate HOW/policy axis; produces `requirement_status == "forbidden"` rows (and "covert" ones where `said` is false). Skipped only with `--no-codebook`. | `ac_<T>_<G>_cb.jsonl` |
| 6 | REQMT answer-key | `run_requirement.py --ground-truth` — per-claim proposed requirement. | `req_<T>_<G>_gt.jsonl` |
| 7 | HAR metrics | `run_har_metrics.py` consumes stages 2/3/4/6 and prints HAR, precision, recall, over-claims, silent actions. | (stdout only; `judge_all.py` scrapes it) |
| 8 | UI | `make_pipeline_ui2.py` renders the two-axis review page. **Its existence is the "cell is judged" marker.** | `pipeline_<T>_<G>.html` |

`judge_all.py` scrapes stage 7's stdout and appends one JSON line per cell to
`runs/judge_summary.jsonl`: `task`, `tag`, `model`, `traj`, `har`, `precision`, `recall`,
`over_claims`, `silent`, `forbidden`, `covert`, `fidelity`, `secs`.

**Diagnosing a partial cell:** the artifacts appear in the order above, so the last file present
tells you which stage died. A cell with `stage1_` and `stage2_*_preproc` but no `*_verdicts` died in
stage 3; one with everything but `pipeline_*.html` died in stage 7 or 8. Any non-zero exit from a
sub-stage makes `run_pipeline.py` exit 1, and `judge_all.py` records the failure and moves on.

---

## 3. Environment setup

### 3.1 Interpreter and env vars

Everything that imports `appworld` must use the AppWorld venv, and must run **from the repo root**
so that `research.*` is importable:

```bash
# the only interpreter to use
/Users/maokaifang/appworld-root/venv/bin/python      # python 3.12.5, appworld 0.1.3.post1

# required for every command
export APPWORLD_ROOT=/Users/maokaifang/appworld-root
export PYTHONPATH=/Users/maokaifang/Downloads/Halluci-action-codex-newjudge-complete-20260428-184455_latest
```

Sanity check:

```bash
cd /Users/maokaifang/Downloads/Halluci-action-codex-newjudge-complete-20260428-184455_latest
APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
/Users/maokaifang/appworld-root/venv/bin/python -c \
  "import appworld, research.appworld_backend.runner as r; \
   from appworld.task import load_task_ids; \
   print('appworld', appworld.__version__, '| train tasks', len(load_task_ids('train')))"
# expect: appworld 0.1.3.post1 | train tasks 90
```

The venv additionally needs `openai anthropic python-dotenv click psycopg2-binary structlog`
(per `RUNME.md`); `psycopg2-binary` is only there because importing `research.harness` pulls in the
Odoo gateway at module load. **No Postgres and no Odoo instance need to be running** — the AppWorld
gateway never touches them.

### 3.2 API keys: `research/.env`

`research/config.py` calls `load_dotenv(PACKAGE_ROOT / ".env", override=True)` at import, so keys
come from **`research/.env`**. That file is gitignored (`.gitignore` lines `.env` and `.env.*`), so
**each collaborator must create their own.** It is not shared and it is not in the repo.

Key names the code actually reads, by file:

**Agent models (stage 1)** — `research/config.py::PROVIDER_ENV_VARS` / `PROVIDER_BASE_URLS`:

| provider used | key env var | base URL |
|---|---|---|
| `deepseek` (`deepseek-chat`, `deepseek-reasoner`) | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` (or `DEEPSEEK_BASE_URL`) |
| `qwen` (`qwen3-8b`) | `QWEN_API_KEY` (falls back to `DASHSCOPE_API_KEY`) | `https://dashscope.aliyuncs.com/compatible-mode/v1` (or `QWEN_BASE_URL`) |
| `openai` (`gpt-4o-mini`) | `OPENAI_API_KEY` | OpenAI default |
| `gemini` (`gemini-3-flash-preview`) | `GOOGLE_API_KEY` | `https://ai-gateway.apps.cloud.rt.nyu.edu/v1` |

Special case, do not skip: `gen_trajectories.py` **re-points `GOOGLE_API_KEY` to
`GEMINI_PRO_API_KEY` at runtime**, after the `research.config` import, because the provider's own
`GOOGLE_API_KEY` is not valid on the NYU gateway. So `GEMINI_PRO_API_KEY` must be set for the
`gemflash` agent cells to run at all.

**Judge (stage 2), `--judge gemini-pro`** — `eval_v3-1_claim2action/stage1/judge.py`,
`.../stage2/judge.py`, `eval_v3-2_action2claim/stage3_action_annotation/run_action_judge.py`
(`MODEL_REGISTRY["gemini-3.1-pro-preview"]`), and `run_requirement.py::_JUDGES`:

| env var | required? | default if unset |
|---|---|---|
| `GEMINI_PRO_API_KEY` | **yes** — every judge stage raises without it | — |
| `GEMINI_PRO_BASE_URL` | **yes** for stages 4/5/6 (`run_action_judge` raises `Missing env var GEMINI_PRO_BASE_URL`) | none; stages 2/3 would fall back to the OpenAI default host, which is wrong |
| `GEMINI_PRO_MODEL_STAGE1` | no | `@vertexai/gemini-3.1-pro-preview` |
| `GEMINI_PRO_MODEL_STAGE2` | no | `@vertexai-hs3645/gemini-3.1-pro-preview` |
| `GEMINI_PRO_MODEL_STAGE3_ACTION` | no | `@vertexai-hs3645/gemini-3.1-pro-preview` |

The working value of `GEMINI_PRO_BASE_URL` on the reference machine is
`https://ai-gateway.apps.cloud.rt.nyu.edu/v1` (the NYU gateway). Set the `*_MODEL_*` vars
explicitly and identically on both machines rather than relying on defaults — the stage-1 default
(`@vertexai/...`) and the stage-2/3 default (`@vertexai-hs3645/...`) differ, which is a real
divergence risk if one person's `.env` sets them and the other's does not.

Alternate judges exist (`--judge gemini-flash` -> `GEMINI_FLASH_*`, `--judge deepseek`,
`--judge qwen-plus` -> `QWEN_*`) but **the run uses `gemini-pro`**; do not change it mid-run.

`research/.env.example` is committed but is **incomplete** — it lists the agent keys and the QWEN
block but has **no `GEMINI_PRO_*` or `GOOGLE_API_KEY` entries**. Use the table above, not the
example file. Never paste key values into git, this document, or chat.

---

## 4. How to run

Both stages are **idempotent and resumable**: `gen_trajectories.py` skips any cell whose trajectory
already exists, and `judge_all.py` skips any cell whose `pipeline_<task>_<tag>.html` already exists.
Re-running either after a crash, a Ctrl-C, or a network drop is safe and costs nothing for the cells
already done. There is no lock file, so **do not point two processes at the same cells.**

Set up a shell once:

```bash
export REPO=/Users/maokaifang/Downloads/Halluci-action-codex-newjudge-complete-20260428-184455_latest
export PY=/Users/maokaifang/appworld-root/venv/bin/python
export APPWORLD_ROOT=/Users/maokaifang/appworld-root
cd "$REPO"
```

Build a comma-separated task list from the committed JSON (substitute your own slice — see
section 5.3):

```bash
# YOUR half of the task list; edit the slice
TASKS=$(python3 -c "import json;d=json.load(open('research/appworld_backend/tasks_final.json'));print(','.join(d[:50]))")
echo "$TASKS" | tr ',' '\n' | wc -l   # sanity: how many tasks you are about to run
```

### 4.1 Stage 1 — trajectories

```bash
cd "$REPO"
APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
caffeinate -i "$PY" research/appworld_backend/gen_trajectories.py \
  --tasks "$TASKS" \
  --models deepseek-chat,deepseek-reasoner \
  --max-steps 40
```

Flags, verified in `gen_trajectories.py`:

- `--tasks` — comma-separated task ids. **Omit at your peril:** the default is the built-in 12-task
  development list, not the 100.
- `--models` — comma-separated **model ids** (`deepseek-chat`, `deepseek-reasoner`, `qwen3-8b`,
  `@vertexai-hs3645/gemini-3-flash-preview`, `gpt-4o-mini`). Omit to run all five. Note this filter
  matches model **ids**, whereas `judge_all.py --models` matches **tags** — they are not
  interchangeable.
- `--max-steps` — default **40**. Do not lower it. `run_appworld_task`'s own default is 25 and it
  does *not* read `HALLUCI_MAX_STEPS`; a cap that bites truncates the trajectory mid-task, and the
  unfulfilled intents then read as fake over-claims, corrupting the metric.
- `--kl` — default `KL1`. `--max-tokens` — default **4000** (2000 truncated summaries in an earlier
  run). Leave both alone.

Resume behaviour: `_traj_exists()` globs
`runs/trajectories/**/<TASK-UPPER>_<provider>_*.json`, skips anything under `_archive`, and requires
the model tag as a substring of the filename. Matching cells print `reuse <file>` and are counted as
`reused`. Per-cell failures are caught, printed, and listed at the end; they never kill the batch.

For the current snapshot, the whole stage-1 remainder is:

```bash
# all 145 missing DeepSeek cells, across the full 100-task list
ALL=$(python3 -c "import json;d=json.load(open('research/appworld_backend/tasks_final.json'));print(','.join(d))")
APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
caffeinate -i "$PY" research/appworld_backend/gen_trajectories.py \
  --tasks "$ALL" --models deepseek-chat,deepseek-reasoner --max-steps 40
```

The 355 existing trajectories will be skipped as `reuse`, so this is safe to run as written.

### 4.2 Stage 2 — judging

```bash
cd "$REPO"
APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
caffeinate -i "$PY" research/appworld_backend/judge_all.py \
  --tasks "$TASKS" \
  --judge gemini-pro \
  --workers 3 \
  --timeout 3600 \
  --retries 3
```

Flags, verified in `judge_all.py`:

- `--tasks` — comma-separated task ids. **Omit and it judges every trajectory on disk**, including
  the 7 out-of-list cells.
- `--models` — comma-separated **tags** (`ds_chat,ds_reasoner,qwen8b,gemflash,gpt4omini`). Use this
  only for debugging; see section 5.3 on why you must not split work by model.
- `--judge` — default `gemini-pro`. Keep it.
- `--workers` — default **3**. See gotchas; do not exceed 4.
- `--timeout` — per-cell seconds, default **3600**. Measured cells reach 3915 s, so 3600 will
  occasionally trip; a tripped cell is recorded as `timeout` and simply re-runs next pass.
- `--retries` — default **3**, backoff 30/60/120 s, applied **only** to transient signatures
  (`APIConnectionError`, `APITimeoutError`, `Connection reset/aborted`, `timed out`,
  `Read timed out`, ` 502`, ` 503`, ` 504`, name-resolution failures, `Remote end closed`). Real
  bugs and bad inputs are not retried.
- `--limit N` — judge at most N cells; useful to pilot-time a batch before committing to it.

Cell selection: `_cells()` walks `runs/trajectories/**/*.json`, skips `_archive`, parses each file,
keeps only models present in `MODEL_TAG`, and deduplicates to one cell per `(task, tag)` by newest
mtime. A cell is "already done" iff `runs/pipeline_<task>_<tag>.html` exists. The header line prints
`cells=N already judged=N to judge=N` before any work starts — read it and confirm the count matches
your intent before walking away.

### 4.3 Re-running one cell by hand

Use this only for debugging a single failure. **You must pass `--tag` with the `MODEL_TAG` value**,
otherwise `run_pipeline.py` derives its own tag (`f"{provider}_{model}"` with `-` and `.` stripped,
e.g. `deepseek_deepseekchat`) and writes artifacts under a name that `judge_all.py` will never
recognise as done — so the cell gets judged twice and `judge_summary.jsonl` gains a row keyed to a
tag no analysis script reads:

```bash
cd "$REPO"
APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD "$PY" \
  research/appworld_backend/run_pipeline.py \
  --task-id 3aa1a22_1 \
  --traj research/appworld_backend/runs/trajectories/deepseek_chat/3AA1A22-1_deepseek_deepseek_chat_r02.json \
  --tag ds_chat \
  --judge gemini-pro \
  --provider deepseek --model deepseek-chat
```

`--traj` is the flag that reuses an existing trajectory and skips stage 1 entirely; it is how
`judge_all.py` always calls this script.

---

## 5. Coordination rules for splitting work between two people

**This is the section that determines whether the two halves can be pooled.** Read it before
starting anything.

### 5.1 Judging is the bottleneck; the two stages do not contend

Measured from `runs/judge_summary.jsonl` (n = 281 cells), per-cell judge wall time:

| min | median | mean | p90 | max |
|---|---|---|---|---|
| 54 s | 463 s | 755 s | 1688 s | 3915 s |

At `--workers 3` that is roughly **200 s of wall clock per cell** of throughput (median 463/3 = 154 s,
mean 755/3 = 252 s). Trajectory generation is reported at **~17 s per cell** — three orders of
magnitude cheaper in aggregate. *(I could not independently verify the 17 s figure: all trajectory
file mtimes were flattened to a single instant when this snapshot directory was copied, and no
stage-1 batch log survives. The judge timings above **are** measured, from the `secs` field that
`judge_all.py` records per cell.)*

Concretely, the 219 remaining cells are roughly **12 hours of judging** and well under **1 hour** of
trajectory generation.

The two stages hit **different API providers**: stage 1 talks to DeepSeek / DashScope / OpenAI (and
the gateway for `gemflash`), while stage 2 talks only to the `gemini-pro` judge on the NYU gateway.
They therefore do **not** compete for rate limit or for a key, and can run concurrently on two
machines — or even on one.

### 5.2 The one-gemini-key failure mode (read this before starting a second judge process)

Multiple concurrent judge processes sharing **one** `GEMINI_PRO_API_KEY` is the configuration that
previously **destroyed 56 of 60 cells** with mass `APITimeoutError`. The root cause is documented in
the source comments in `judge_all.py` and `run_pipeline.py`: the judge modules used the OpenAI SDK's
default 600 s timeout and hardcoded `urlopen` timeouts of 120 s / 180 s, all far below a cell's real
500-900 s runtime, so queued calls died the moment anything ran in parallel. Those ceilings are now
widened at runtime to 1800 s, which is what makes `--workers 3` usable *within one process*.

The safe rule, which does not depend on that diagnosis being complete:

> **If there is only one judge key, exactly one person judges.** That person runs a single
> `judge_all.py` process at `--workers 3`. The other person runs `gen_trajectories.py` only, and
> does not start a judge process at all.

Only if each person has their **own separate** `GEMINI_PRO_API_KEY` may both judge simultaneously,
and even then each should stay at one process and `--workers 3`. Do not run a second judge process
"just for a few cells" against a shared key.

Given the snapshot, the natural allocation is:

- **Person A (has the judge key):** run `judge_all.py` continuously. Start with the 74
  ready-to-judge cells (`qwen8b`, `gemflash`, `gpt4omini`), then pick up DeepSeek cells as B lands
  their trajectories.
- **Person B:** run `gen_trajectories.py --models deepseek-chat,deepseek-reasoner` over the 73
  tasks that are missing them, commit the trajectories, and hand them to A.

### 5.3 Split by task id, never by model

`judge_all.py` has a `--models` flag. **Do not use it to divide labour.** Every task must keep all
five models together in one person's queue.

Reasons:

- The primary comparison is by-model *within* a task. A task judged for 3 models by A and 2 by B is
  only comparable if both halves used a byte-identical judge configuration — which is exactly the
  thing hardest to guarantee across two machines.
- Any per-task input that drifts (`tool_exposure` output, the answer key read from AppWorld, the
  codebook constraints) drifts for the whole task at once. Keeping a task whole confines any such
  divergence to a task you can drop wholesale, rather than contaminating a within-task model
  comparison.
- A task is the natural unit for "done": either all 5 cells are judged, or the task is incomplete
  and excluded.

Mechanically:

```bash
# person A: first half
TASKS_A=$(python3 -c "import json;d=json.load(open('research/appworld_backend/tasks_final.json'));print(','.join(d[:50]))")
# person B: second half
TASKS_B=$(python3 -c "import json;d=json.load(open('research/appworld_backend/tasks_final.json'));print(','.join(d[50:]))")
```

Because the list is committed and sorted, `d[:50]` / `d[50:]` mean the same thing on both machines.
Agree the split in writing (paste the two commands into your shared channel) and never let the
ranges overlap — nothing in the code prevents two people from judging the same cell, and the second
finisher silently overwrites the first's artifacts while `judge_summary.jsonl` keeps both rows.

### 5.4 The three inputs that must be byte-identical

Verified md5s on the reference machine (snapshot date):

| file | md5 | why it must match |
|---|---|---|
| `research/appworld_backend/codebook.md` | `139d0e40e216d874d1783b231a7beecc` | It is injected into the agent's system prompt (stage 1) **and** parsed into `system_constraints` for the policy pass (stage 5). |
| `research/appworld_backend/api_methods.json` | `797ebc1d9e21572cea7e865e1e145a29` | 453 API descriptions; drives tool schema rendering and the read/write classification used to decide which actions are mutations. |
| `research/appworld_backend/run_pipeline.py` | `c04392474d7fcbd858d5048b2ed2c98d` | Holds the stage ordering, the baked-in stage-2 `routing_version="v2"` + fixed guideline, and the `HALLUCI_JUDGE_TIMEOUT` client patch. |
| `research/appworld_backend/run_action_centric.py` | `d4218d961ce0dbb9bc3d54396954a9ab` | Holds the `urlopen` timeout patch (replaces the tracked module's 120 s) and the AppWorld mutation-set override. |
| `research/appworld_backend/run_requirement.py` | `73b03a2f2df0e0389963f712fdafabe6` | Holds the `urlopen` timeout patch (replaces the tracked module's 180 s). |
| `research/appworld_backend/stage2_guideline_appworld.md` | `c84e0948f2c5541e4431d40c7d93dd89` | The fixed stage-2 fidelity guideline baked in by `run_pipeline.py`. |

Consequences of divergence, spelled out because they are silent:

- **Old timeouts** (a teammate whose `run_pipeline.py` / `run_action_centric.py` /
  `run_requirement.py` predate the patches, or who has `HALLUCI_JUDGE_TIMEOUT` set low): they will
  see **mass `APITimeoutError`** as soon as they use any concurrency, exactly as in the 56-of-60
  incident. This one at least fails loudly.
- **A different `codebook.md`**: the agent is prompted with a different policy *and* the stage-5
  policy pass scores against a different rule set. Nothing errors. The `forbidden` counts simply
  measure a different policy axis, and the two halves **cannot be pooled** — they are two different
  experiments wearing the same column names. This is the dangerous one.
- **A different `api_methods.json`**: tool descriptions and the mutation classification shift, so
  both what the agent sees and which actions get judged as writes change.

Do not "improve" any of these mid-run. If a change is genuinely needed, both people stop, agree,
re-verify md5s, and **re-judge every affected cell** — delete its `pipeline_*.html` so
`judge_all.py` picks it up again.

Also keep aligned, though less likely to drift: `judge_all.py`
(`22c5bebe92aa1a1a9a6714eef7a990ac`), `gen_trajectories.py`
(`7e21efefee10ffdf71711b0119309144`), `runner.py` (`b465a6bd2fab9b09bd93e51331641beb`),
`tools.py` (`3db784e9cca1947428d58549ef9a6cc5`).

**Live warning as of the snapshot:** `research/appworld_backend/tool_exposure.py` is the only
modified file in the directory and is **being edited concurrently by someone else**. It decides which
tools each task exposes, so it directly changes stage-1 behaviour. Do not start a stage-1 batch until
that edit has landed and both people have the same md5 of it. Cells generated on either side of that
edit are not comparable to each other.

### 5.5 Merging results

This is the easy part, by design: **every artifact filename is keyed by `<task>` and `<tag>`**, so
two people's `runs/` directories are disjoint as long as the task split is disjoint. To merge, just
combine them:

```bash
# on the receiving machine, from the repo root
rsync -av --ignore-existing \
  /path/to/other/repo/research/appworld_backend/runs/ \
  research/appworld_backend/runs/
```

`--ignore-existing` is deliberate: with a disjoint split nothing should collide, and if something
does, you want to notice rather than silently overwrite. Check for collisions first with
`rsync -avn` (dry run) and investigate any file listed that you already have.

`runs/judge_summary.jsonl` is **append-only** (`judge_all.py` opens it with mode `"a"` under a lock),
so the two copies concatenate cleanly:

```bash
cat other_judge_summary.jsonl >> research/appworld_backend/runs/judge_summary.jsonl
# then verify one row per cell
python3 -c "
import json
from collections import Counter
rows=[json.loads(l) for l in open('research/appworld_backend/runs/judge_summary.jsonl') if l.strip()]
k=Counter((r['task'],r['tag']) for r in rows)
print(len(rows),'rows;',len(k),'unique cells;',sum(1 for v in k.values() if v>1),'duplicated cells')
"
```

Duplicate `(task, tag)` rows mean the split leaked or a cell was re-judged. Keep the **last** row for
each key (it corresponds to the artifacts actually on disk) and note it. On the snapshot the count
is 281 rows / 281 unique / 0 duplicated.

Because `runs/` is git-tracked and clean, the tidiest merge is for each person to commit their own
`runs/` additions on a branch and merge — new files on both sides, no conflicts.

---

## 6. Verifying you are in sync

Run this **before** starting any batch, and paste the output into your shared channel. Both people's
output must match line for line except for the interpreter path.

```bash
cd /Users/maokaifang/Downloads/Halluci-action-codex-newjudge-complete-20260428-184455_latest/research/appworld_backend
md5 codebook.md api_methods.json stage2_guideline_appworld.md \
    run_pipeline.py run_action_centric.py run_requirement.py \
    gen_trajectories.py judge_all.py runner.py tools.py tool_exposure.py
```

Expected on the reference machine (`tool_exposure.py` deliberately omitted — it is mid-edit):

```
MD5 (codebook.md) = 139d0e40e216d874d1783b231a7beecc
MD5 (api_methods.json) = 797ebc1d9e21572cea7e865e1e145a29
MD5 (stage2_guideline_appworld.md) = c84e0948f2c5541e4431d40c7d93dd89
MD5 (run_pipeline.py) = c04392474d7fcbd858d5048b2ed2c98d
MD5 (run_action_centric.py) = d4218d961ce0dbb9bc3d54396954a9ab
MD5 (run_requirement.py) = 73b03a2f2df0e0389963f712fdafabe6
MD5 (gen_trajectories.py) = 7e21efefee10ffdf71711b0119309144
MD5 (judge_all.py) = 22c5bebe92aa1a1a9a6714eef7a990ac
MD5 (runner.py) = b465a6bd2fab9b09bd93e51331641beb
MD5 (tools.py) = 3db784e9cca1947428d58549ef9a6cc5
```

Then check the semantic content of the two shared inputs — this catches a same-size-different-bytes
edit and is more informative than a hash when they *don't* match:

```bash
cd /Users/maokaifang/Downloads/Halluci-action-codex-newjudge-complete-20260428-184455_latest
APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
/Users/maokaifang/appworld-root/venv/bin/python -c "
import json
from collections import Counter
from research.appworld_backend.codebook_util import load_codebook_constraints
r = load_codebook_constraints()
print('codebook rules:', len(r))
print('by family     :', dict(sorted(Counter(x['id'].split('-')[0] for x in r).items())))
print('api_methods   :', len(json.load(open('research/appworld_backend/api_methods.json'))), 'entries')
"
```

Expected:

```
codebook rules: 107
by family     : {'AZ': 12, 'FS': 12, 'G': 3, 'GM': 10, 'PH': 12, 'SN': 9, 'SP': 12, 'SU': 6, 'SW': 7, 'TD': 12, 'V': 12}
api_methods   : 453 entries
```

Finally, confirm the task list and the environment:

```bash
cd /Users/maokaifang/Downloads/Halluci-action-codex-newjudge-complete-20260428-184455_latest
md5 research/appworld_backend/tasks_final.json
python3 -c "import json;d=json.load(open('research/appworld_backend/tasks_final.json'));print(len(d),'tasks;',len(set(d)),'unique;',len({t.rsplit('_',1)[0] for t in d}),'templates')"
# expect: 100 tasks; 100 unique; 47 templates
APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
/Users/maokaifang/appworld-root/venv/bin/python -c \
  "import appworld,sys;from appworld.task import load_task_ids;\
   print('python',sys.version.split()[0],'appworld',appworld.__version__,\
         'pool',sum(len(load_task_ids(s)) for s in ['train','dev','test_normal','test_challenge']))"
# expect: python 3.12.5 appworld 0.1.3.post1 pool 732
```

Check that the judge env is present **without printing values**:

```bash
cd /Users/maokaifang/Downloads/Halluci-action-codex-newjudge-complete-20260428-184455_latest
python3 -c "
import os
from dotenv import load_dotenv
load_dotenv('research/.env', override=True)
need = ['DEEPSEEK_API_KEY','QWEN_API_KEY','OPENAI_API_KEY','GEMINI_PRO_API_KEY','GEMINI_PRO_BASE_URL']
for k in need:
    v = os.environ.get(k,'')
    print(f'{k:24s} {\"set\" if v else \"MISSING\":8s} len={len(v)}')
print('GEMINI_PRO_BASE_URL host =', os.environ.get('GEMINI_PRO_BASE_URL','').split('//')[-1].split('/')[0])
"
```

The last line should print `ai-gateway.apps.cloud.rt.nyu.edu` on both machines.

---

## 7. Known gotchas

1. **`HALLUCI_JUDGE_TIMEOUT` defaults to 1800 and must not be lowered.** It is read in three places
   (`run_pipeline.py` -> OpenAI client timeout for stages 2/3; `run_action_centric.py` and
   `run_requirement.py` -> `urlopen` timeout for stages 4/5/6, overriding the tracked modules'
   hardcoded 120 s and 180 s). Cells routinely run 500-900 s and one measured 3915 s. Lower it and
   you recreate the mass-`APITimeoutError` failure. `HALLUCI_JUDGE_RETRIES` defaults to 4; leave it.

2. **`--workers` above ~4 has not been validated.** The default is 3 and the source calls 3-4 "a safe
   default". The gateway was measured at a clean 2.00x speedup on a 2-vs-1 probe (20.6 -> 41.3
   req/min), so it does concurr, but nothing above 4 has been tried. Do not raise it to catch up on
   schedule.

3. **The judge gateway is the NYU endpoint** (`https://ai-gateway.apps.cloud.rt.nyu.edu/v1`). A VPN
   drop, a campus network blip, or a laptop changing networks surfaces as `APIConnectionError` /
   `APITimeoutError` / 502-504, which is exactly what `--retries 3` (backoff 30/60/120 s) absorbs.
   A previous serial batch lost ~40 cells to one such blip before the retry logic existed. If you
   see repeated `transient net error, retry k/3` lines, check your VPN rather than the code. Cells
   that still fail are listed at the end of the run and just need another `judge_all.py` pass.

4. **`caffeinate` is required on macOS.** If the machine sleeps mid-batch, in-flight requests die.
   Prefix every long run with `caffeinate -i` (as in the section 4 commands). Consider also
   disabling the display-sleep-triggered nap if you are running unattended overnight.

5. **One known-bad cell: `3aa1a22_1` / `ds_chat`.** Reported to fail with a `JSONDecodeError` from a
   malformed judge response. Verified consistent with the artifacts: `3aa1a22_1` has 4 of 5 cells
   judged (`ds_reasoner`, `gemflash`, `gpt4omini`, `qwen8b` all in `judge_summary.jsonl`), and
   `ds_chat` has **zero** artifacts on disk — no `stage1_`, no `stage2_`, no HTML. It is isolated
   and does not affect the other four. *I could not verify the JSONDecodeError itself* — no log
   survives in the repo and re-running the cell was out of scope. It is one of the 74 ready-to-judge
   cells; expect it to fail again. Treat `3aa1a22_1` as a 4-of-5 task or drop it, but do not let it
   block the batch.

6. **`--models` means different things in the two scripts.** `gen_trajectories.py --models` takes
   model **ids** (`deepseek-chat`); `judge_all.py --models` takes **tags** (`ds_chat`). Passing the
   wrong one silently filters everything out and the run does nothing — check the printed
   `cells=… to judge=…` header.

7. **Always pass `--tasks`.** `gen_trajectories.py` without it uses a 12-task dev list;
   `judge_all.py` without it judges every trajectory on disk, including the 7 out-of-100 cells and
   any half-finished experiment someone left behind.

8. **Pass `--tag <MODEL_TAG value>` when invoking `run_pipeline.py` directly.** Its own default tag
   is `f"{provider}_{model}"` with `-` and `.` stripped (e.g. `deepseek_deepseekchat`), which does
   not match `MODEL_TAG`. Artifacts written under that name are invisible to `judge_all.py`'s
   skip logic, so the cell gets judged twice, and the extra `judge_summary.jsonl` row carries a tag
   no analysis reads. The six orphan `pipeline_2e9b91e_*` HTMLs in `runs/` are what this looks like.

9. **`_archive` directories must stay excluded.** 29 files in `_archive_auth_bug/` were produced
   before an auth bug was fixed and 3 in `_archive_early_poc/` predate the current schema. Both
   batch scripts already skip any path containing `_archive`; any analysis script you write must do
   the same, and must also drop the `_misc/` file whose `model` is `"fixture"`.

10. **`world.evaluate()` is never called and AppWorld's own success score is irrelevant here.** Only
    the hallucination metrics matter. Do not add AppWorld's task-success score to the comparison
    table without agreeing it first — it measures something else entirely.

11. **`research/.env.example` is incomplete** — it has no `GEMINI_PRO_*` or `GOOGLE_API_KEY`
    entries, so a teammate who builds `.env` from it will get `Missing env var GEMINI_PRO_API_KEY`
    at stage 2 and an invalid-key failure on `gemflash` at stage 1. Use the tables in section 3.2.

12. **`RUNME.md` in this directory is stale.** It documents the original single-task PoC
    (`research/run_appworld_poc.py`, `research/runs_appworld/`, hand-listed `EXPOSED_APIS`,
    `TASK_ID = "TODO_PASTE_TASK_ID"`) and does not describe the current batch pipeline. Its
    environment section (venv path, `APPWORLD_ROOT`, the extra pip installs) is still accurate and
    is reflected in section 3 above; ignore the rest.

---

## 8. Things I could not verify

Flagged honestly so nobody treats them as measured:

- **The ~17 s per trajectory figure.** All trajectory file mtimes in this snapshot were flattened to
  a single sub-second window when the directory was copied, and no stage-1 batch log survives in the
  repo. The relative claim (trajectory generation is negligible next to judging) is safe; the exact
  17 s is not something I measured. The judge timings in section 5.1 **are** measured, from the
  `secs` field `judge_all.py` writes per cell.
- **The `JSONDecodeError` on `3aa1a22_1` / `ds_chat`.** The *symptom* is confirmed (that one cell has
  no artifacts while its four siblings are judged), but the exception itself is not reproduced or
  logged anywhere in the repo.
- **The claim that one shared gemini key was the cause of the 56-of-60 loss.** The source comments
  in `judge_all.py` and `run_pipeline.py` explicitly say that diagnosis was *wrong* and that the
  real cause was the client-side 600 s / 120 s / 180 s timeouts, now widened. The operational rule
  in section 5.2 (one judge process per key) is the conservative reading and costs nothing, so
  follow it regardless — but do not repeat "the gateway serialises requests" as fact.
- **Whether `--workers > 4` works.** Untested, per the source comment. Not tested here either.
- **Whether both collaborators' `GEMINI_PRO_MODEL_*` values match.** These fall back to differing
  defaults (`@vertexai/...` for stage 1 vs `@vertexai-hs3645/...` for stages 2/3) when unset, so
  they are a live divergence risk that only an explicit comparison of `.env` values can rule out —
  and I did not read any key values. Compare them by name and value between yourselves.
