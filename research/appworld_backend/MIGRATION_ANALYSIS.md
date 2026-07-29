# AppWorld migration — analysis (one page)

*Current version = an ADDITIVE layer in `research/appworld_backend/`. AppWorld's
installed package and Halluci-Action's tracked code are unmodified (git-verified).
"Modifications" below mean how AppWorld is **driven**, not edits to its engine.*

## 0. What changed vs original AppWorld

| Aspect | AppWorld original | This version |
|---|---|---|
| Agent | code agent (`world.execute` code blocks) | **in-process tool-calling** (harness drives calls; executor → `world.apis`) |
| Eval target | task success, DB unit tests (TGC/SGC), `world.evaluate()` | **never** `world.evaluate`; runs the halluci judge → HAR (claim vs reality) |
| Policy doc | none | injects **`codebook.md`** (soft constraints) into the system prompt |
| System prompt | "full access / never ask / batch" | neutral + narration + KL + codebook (opposite posture) |
| State audit | per `world.execute` (code-block) | **per tool call** (`save_state` before/after → per-action `state_delta`) |
| Tool exposure | 457 APIs, agent self-discovers via api_docs | hand-curated small subset per task (`EXPOSED_APIS`), auth auto-injected |
| Ground truth | `solution.py` / `evaluation.py` for self-scoring | reuse `test_data.json` (NL outcome spec) as answer key; discard `evaluation.py` |
| Judge glue | (Odoo layout) | 3 monkeypatches (task lookup, stage-1 path, `app__` naming) + session fixes (v2 routing, guideline, two-axis UI, max_tokens 4000) |

Engine and world are used as-is; what changed is *how the agent runs, what is
scored, the added codebook, and per-action auditing*.

## 1. Task diversity (measured, 732 tasks)

- **splits**: train 90 · dev 57 · test_normal 168 · test_challenge 417 = **732**
- **244 scenario families, each with exactly 3 parametric variants** (`_1/_2/_3`; e.g. roommates/siblings/coworkers)
- **type**: ~**82% state-changing** (603) vs 129 answer-seeking (heuristic) — good, most commit writes
- **cross-app**: of the 147 measurable, 96 single-app · 45 two-app · 6 three-app (~35% cross-app)
- **9 consumer apps**; 4 difficulty tiers

**HA caveat**: this diversity is for *task completion*, not *HA induction*. AppWorld
does not systematically vary the 7 HA types; ambiguity (same-name people) is a
byproduct, not a design axis. HA-relevant richness = *consequential-juncture density*,
which is uneven (money/comm apps dense; content apps thin). **Only 147/732 ship
`solution.py`** (step-level ground truth); the other 585 have only `test_data.json`
(outcome spec). Net: task volume/variants are high, but **HA material must be
selected (by juncture density) and designed (planted traps), not assumed**.

## 2. Elements to modify (status)

| # | Element | Status |
|---|---|---|
| 1 | Agent → tool-calling | ✅ |
| 2 | Discard `world.evaluate`, attach judge | ✅ |
| 3 | Codebook (soft constraints) | ✅ 50 rules: 3 Global + Venmo 12 + Amazon 12 + Gmail 10 + Supervisor 6 + Splitwise 7 (each cites a real API default; Splitwise deliberately lighter — recoverable deletes → disclose-after). Spotify/Phone/Todoist/Note/FS: Global-only by design (§2.5) |
| 4 | `ground_truth_steps` derivation | ✅ (147 via solution.py, 585 via test_data) |
| 5 | Tool-subset exposure policy | ✅ systematized: `tool_exposure.py` — REAL = involved-app CORE (coverage-guaranteed) + DISTRACTORS = round(REAL×ratio) semantic-biased (same/adjacent-domain ACTION tools, seeded). Curated cores for 9 apps + domain/adjacency maps; supervisor excluded (authz-trap only); `run_pipeline --exposed-apis auto`. Core-curation + instruction-parse detection still want a review pass |
| 6 | Prompt rewrite | ✅ |
| 7 | Judge monkeypatches (task/stage1/`app__`) | ✅ |
| 8 | Judge metric fixes (v2 routing, guideline, two-axis UI, max_tokens) | ✅ this session |
| 9 | Route per-tool `state_delta` into Stage-2 | ❌ (slim_audit drops it) |
| 10 | `active_constraints_for_task()` AppWorld port | ❌ (uses full codebook for now) |
| 11 | HA-inducing task design / high-density app selection | ❌ (demo runs stock tasks) |
| 12 | Judge domain validation (gold labels) + multi-model | ❌ (1 task, mostly deepseek) |

Free (no change needed): the world, 457 APIs, ~100 related people, deterministic
state + `save_state` checkpoints, same-name people (Substitution), Supervisor
credential fields (Authorization).

## 3. Comparability with the Halluci-Action pipeline

The **pipeline code is largely shared** — same claim2action/action2claim judge, same
4-label rubric, same HAR=1−F1, same codebook mechanism, same two axes. Only the
backend (executor/gateway) and task-def source differ.

| | Shared (comparable) | Different (limits comparability) |
|---|---|---|
| Judge | same code, same rubric, same HAR | v2 routing + extended guideline are an AppWorld-side additive layer (not yet merged upstream) |
| Codebook mechanism | soft policy doc, Global G-01..03 ported verbatim, KL, two axes | app-specific content differs (Venmo AV vs Odoo I/S) — same construct, different domain |
| Claim layer | `claim_pre/post`, supported/not_supported, required/forbidden | — |
| Domain / tool grain | — | consumer apps vs ERP; curated subset vs Odoo's 82 high-level tools |
| Task design | — | AppWorld completion-oriented vs Odoo HA-oriented |
| Reversibility | — | AppWorld writes have **no undo** (sharper than Odoo — makes covert the default risk, not a tail case) |

**Two levels of comparability (keep separate):**
- ✅ **Construct-comparable** (what you want): same HA phenomena, same judge, same
  codebook mechanism, same two axes.
- ❌ **Not number-comparable**: absolute HAR differs by world; this was never the goal.

**Use it right:** compare (a) whether the same HA *types emerge* in both worlds, and
(b) *relative model rankings* across worlds — not absolute HAR (e.g. not 0.291 vs 0.34).
