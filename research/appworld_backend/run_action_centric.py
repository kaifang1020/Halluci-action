"""
Run the ACTION-CENTRIC judge (eval_v3-2 action2claim / stage3) on an AppWorld run.

This is the reverse-direction judge: for every ACTION the agent took, it asks
  (a) was this action narrated by any assistant sentence?  -> `said`
      (`said=False` == a SILENT action, the core halluci-action signal), and
  (b) was this action required / allowed_supporting / unnecessary / forbidden?
      -> `requirement_status` (the severity axis behind RQ1's HAR_severity).

It REUSES the real judge (`research/eval_v3-2_action2claim/stage3_action_annotation/
{build_action_items,run_action_judge}.py`) unchanged — no edits to tracked files.
We only monkeypatch the three Odoo-specific lookups those modules do, because they
assume the Odoo experiment layout:

  1. load_tasks_registry()  -> Odoo TASKS dict; AppWorld task_id isn't in it.
     We supply a minimal task_def built from the AppWorld task itself.
  2. load_stage1_claims()   -> a hardcoded `{task_id}_gemini-pro_v1_judge.json`
     filename; we read OUR stage-1 output file instead.
  3. is_mutation_tool()     -> checks bare prefixes ("create_", ...), but AppWorld
     names are "<app>__<api>" so we strip the "<app>__" first.

Model defaults to deepseek (added to the judge's MODEL_REGISTRY at runtime) so it
matches the stage-1/stage-2 runs and uses a key we know works.

Usage (from the halluci repo root, in the AppWorld venv):
    APPWORLD_ROOT=/Users/maokaifang/appworld-root \
    /Users/maokaifang/appworld-root/venv/bin/python \
        research/appworld_backend/run_action_centric.py \
        --task-id 2e9b91e_1 \
        --traj research/appworld_backend/runs/trajectories/2E9B91E-1_deepseek_deepseek_chat.json \
        --stage1 research/appworld_backend/runs/stage1_2e9b91e_1.json \
        --out research/appworld_backend/runs/action_centric_2e9b91e_1.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
STAGE3 = REPO / "research" / "eval_v3-2_action2claim" / "stage3_action_annotation"
sys.path.insert(0, str(STAGE3))

os.environ.setdefault("APPWORLD_ROOT", "/Users/maokaifang/appworld-root")

import build_action_items as bai  # noqa: E402
import run_action_judge as raj  # noqa: E402

# raj.ChatClient.complete() calls `urlopen(req, timeout=120)`. One judged cell runs
# 500-900s end to end, and the action judge is the busiest stage (it runs twice per cell:
# answer-key + codebook), so under concurrent cells that 120s ceiling is the first thing to
# break -- the failure mode that killed an earlier batch and was misdiagnosed as the gateway
# serialising. A 2-vs-1 probe measured a clean 2.00x, so the gateway is fine; the ceiling
# was ours. Widen it at the urlopen level (runtime override; tracked module not edited).
_JUDGE_HTTP_TIMEOUT = float(os.environ.get("HALLUCI_JUDGE_TIMEOUT", "1800"))
_raj_urlopen = raj.request.urlopen
raj.request.urlopen = lambda req, *a, **kw: _raj_urlopen(
    req, *a, **{**kw, "timeout": max(kw.get("timeout") or 0, _JUDGE_HTTP_TIMEOUT)}
)


def _appworld_task_def(
    task_id: str,
    constraints: list[dict[str, str]] | None = None,
    ground_truth: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Minimal task_def for an AppWorld task, in the shape the judge expects.

    ``constraints`` (from the codebook, via ``--codebook``) populate
    ``system_constraints`` so the judge can flag a `forbidden` action that violates a
    policy rule. Without them the judge sees no policy and cannot mark anything
    forbidden. ``ground_truth_steps`` stays empty (AppWorld ships a programmatic
    ``evaluation.py``, not a step list); the `said` / silent-action axis does not
    depend on either field.
    """
    from appworld import AppWorld

    world = AppWorld(task_id=task_id, experiment_name="action_centric_probe")
    try:
        instr = world.task.instruction
    finally:
        try:
            world.close()
        except Exception:
            pass
    return {
        task_id: {
            "name": instr,
            "domain": "appworld",
            "difficulty": None,
            "system_constraints": constraints or [],
            "ground_truth_steps": ground_truth or [],
        }
    }


def _strip_app_prefix(tool_name: str) -> str:
    return tool_name.split("__", 1)[1] if "__" in tool_name else tool_name


def _appworld_mutation_set(task_id: str, traj_path: Path, orig_is_mut) -> set[str]:
    """Return the set of `app__api` tool names in this trajectory that MUTATE state,
    decided by each API's real HTTP method (GET = read, POST/PUT/PATCH/DELETE = write).
    This replaces the Odoo-verb prefix heuristic in build_action_items.is_mutation_tool,
    which misses AppWorld writes like amazon__place_order / splitwise__record_expense /
    amazon__subscribe_prime. Falls back to the prefix heuristic if a doc lookup fails."""
    tools: set[str] = set()
    tj = json.loads(Path(traj_path).read_text(encoding="utf-8"))
    for s in tj.get("steps", []):
        for tc in (s.get("tool_calls") or []):
            if tc.get("tool_name"):
                tools.add(tc["tool_name"])
    # prefer the prebuilt global table (research/appworld_backend/api_methods.json = every
    # API's real HTTP method); only tools missing from it fall back to a live lookup.
    table_path = Path(__file__).resolve().parent / "api_methods.json"
    table = json.loads(table_path.read_text(encoding="utf-8")) if table_path.exists() else {}
    muts: set[str] = set()
    missing = []
    for full in tools:
        if full in table:
            if table[full].get("is_write"):
                muts.add(full)
        else:
            missing.append(full)
    if missing:  # rare: tool not in the table -> live method lookup, else prefix heuristic
        try:
            from appworld import AppWorld
            w = AppWorld(task_id=task_id, experiment_name="mutation_probe")
            try:
                for full in missing:
                    app, _, api = full.partition("__")
                    try:
                        method = str(w.apis.api_docs.show_api_doc(app_name=app, api_name=api).get("method", "")).upper()
                        if method and method != "GET":
                            muts.add(full)
                    except Exception:
                        if orig_is_mut(_strip_app_prefix(full)):
                            muts.add(full)
            finally:
                w.close()
        except Exception:
            for full in missing:
                if orig_is_mut(_strip_app_prefix(full)):
                    muts.add(full)
    return muts


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--task-id", required=True)
    p.add_argument("--traj", type=Path, required=True, help="trajectory json (repo-relative or absolute)")
    p.add_argument("--stage1", type=Path, required=True, help="our stage-1 claims json")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--model", default="deepseek")
    p.add_argument("--ground-truth", action="store_true",
                   help="ANSWER-KEY slot (recommended): inject the task's resolved test_data "
                        "outcome spec as ground_truth_steps. This is what required/forbidden "
                        "should be judged against, mirroring Odoo's tasks.py answer key.")
    p.add_argument("--codebook", type=Path, default=None,
                   help="EXPERIMENTAL — do NOT use for the main HAR/severity flow. The codebook "
                        "is the agent-facing policy and belongs in a separate pass4-style "
                        "adherence audit, NOT in this judge's system_constraints. Feeding it here "
                        "mixes WHAT (was the action right?) with HOW (did it follow policy?) and "
                        "can flip a correct-outcome action to `forbidden`. Kept only for A/B tests.")
    args = p.parse_args()

    stage1_path = args.stage1 if args.stage1.is_absolute() else REPO / args.stage1
    traj_path = args.traj if args.traj.is_absolute() else REPO / args.traj
    rel_traj = str(traj_path.resolve().relative_to(REPO / "research"))

    constraints = None
    if args.codebook:
        from codebook_util import load_codebook_constraints
        constraints = load_codebook_constraints(args.codebook)
        print(f"injected {len(constraints)} codebook rules as system_constraints")

    ground_truth = None
    if args.ground_truth:
        from ground_truth_util import load_ground_truth_outcomes
        ground_truth = load_ground_truth_outcomes(args.task_id)
        print(f"injected {len(ground_truth)} ground-truth outcomes as ground_truth_steps")

    # --- monkeypatch the 3 Odoo-coupled lookups ---
    task_registry = _appworld_task_def(args.task_id, constraints, ground_truth)
    bai.load_tasks_registry = lambda: task_registry

    stage1_by_step = {int(s["step_id"]): (s.get("claims") or [])
                      for s in json.loads(stage1_path.read_text(encoding="utf-8"))}
    bai.load_stage1_claims = lambda task_id, metadata, stage1_dir: dict(stage1_by_step)

    # mutation detection by real HTTP method (not the Odoo-verb prefix list, which misses
    # place_order / record_expense / subscribe_prime / reply_to_email / ... on AppWorld)
    _orig_is_mut = bai.is_mutation_tool
    _MUT = _appworld_mutation_set(args.task_id, traj_path, _orig_is_mut)
    bai.is_mutation_tool = lambda tool_name: (tool_name or "") in _MUT
    print(f"mutation tools (by HTTP method): {sorted(_MUT)}")

    # --- add deepseek to the judge's model registry (OpenAI-compatible POST) ---
    raj.MODEL_REGISTRY["deepseek"] = {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "model_env": "DEEPSEEK_MODEL_STAGE3_ACTION",
        "default_model": "deepseek-chat",
    }
    os.environ.setdefault("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    # qwen-plus is the qwen JUDGE backend: non-thinking, so the judges' non-streaming
    # calls work without the enable_thinking=false flag that qwen3-8b requires.
    raj.MODEL_REGISTRY["qwen-plus"] = {
        "api_key_env": "QWEN_API_KEY",
        "base_url_env": "QWEN_BASE_URL",
        "model_env": "QWEN_MODEL_QWENPLUS",  # normally unset -> default_model
        "default_model": "qwen-plus",
    }

    # --- build one item per action, then judge each ---
    items = bai.build_items(trajectories={args.task_id: rel_traj})
    print(f"built {len(items)} action items from {rel_traj}")

    client = raj.resolve_client(args.model)
    preds: list[dict] = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for it in items:
            prompt = raj.render_prompt(it)
            try:
                raw = client.complete(prompt)
                obj = raj.extract_json_object(raw)
                pred = raj.normalize_prediction(it, obj, raw=raw)
            except Exception as exc:  # noqa: BLE001
                pred = raj.normalize_prediction(it, {}, error=str(exc))
            preds.append(pred)
            f.write(json.dumps(pred, ensure_ascii=False) + "\n")
            print(f"  {pred['action_id']:20s} {pred['tool_name']:32s} "
                  f"said={pred['said']!s:5} req={pred['requirement_status']}")

    # --- summary ---
    n = len(preds)
    silent = [x for x in preds if not x["said"]]
    print("\n=== ACTION-CENTRIC SUMMARY ===")
    print(f"actions judged: {n}")
    print(f"silent (said=False): {len(silent)}  -> {[x['tool_name'] for x in silent]}")
    print("requirement_status:", dict(Counter(x["requirement_status"] for x in preds)))
    mutations = [x for x in preds if bai.is_mutation_tool(x["tool_name"])]
    silent_mut = [x for x in mutations if not x["said"]]
    forbidden = [x for x in preds if x["requirement_status"] == "forbidden"]
    print(f"mutating actions: {len(mutations)}  | silent mutations: {len(silent_mut)}")
    print(f"forbidden actions: {len(forbidden)}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
