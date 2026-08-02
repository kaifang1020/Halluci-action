"""
Run the eval_v4 PROPOSED-REQUIREMENT judge (required-miss) on an AppWorld run.

For every action-CLAIM the agent made (action_intention / action_completion), this
judge classifies the requirement status of the referenced action —
  required | allowed_supporting | unnecessary | forbidden | unclear
— which is the input to RQ1's "required action falsely reported complete"
(required-miss) severity component: a claim that asserts a REQUIRED action but has
no executed tool call behind it is a required-miss.

REUSES the real judge (`research/eval_v4/stage2/proposed_requirement/
{build_claim_items,run_requirement_judge}.py`) unchanged. We monkeypatch the two
Odoo-coupled lookups (task registry, stage-1 filename) exactly as in
`run_action_centric.py`, and point the judge's client at deepseek.

Usage (halluci repo root, AppWorld venv):
    APPWORLD_ROOT=/Users/maokaifang/appworld-root \
    /Users/maokaifang/appworld-root/venv/bin/python \
        research/appworld_backend/run_requirement.py \
        --task-id 2e9b91e_1 \
        --traj research/appworld_backend/runs/trajectories/2E9B91E-1_deepseek_deepseek_chat.json \
        --stage1 research/appworld_backend/runs/stage1_2e9b91e_1.json \
        --out research/appworld_backend/runs/requirement_2e9b91e_1.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
PR_DIR = REPO / "research" / "eval_v4" / "stage2" / "proposed_requirement"
sys.path.insert(0, str(PR_DIR))

os.environ.setdefault("APPWORLD_ROOT", "/Users/maokaifang/appworld-root")

# load research/.env so judge keys (GEMINI_PRO_API_KEY / DEEPSEEK / QWEN) are present
# even when this CLI is run standalone (rrj doesn't load it itself).
try:
    from dotenv import load_dotenv
    load_dotenv(REPO / "research" / ".env", override=True)
except Exception:
    pass

import build_claim_items as bci  # noqa: E402
import run_requirement_judge as rrj  # noqa: E402

# Same fix as run_action_centric: rrj.ChatClient.complete() hardcodes urlopen(timeout=180),
# which is far below a judged cell's real 500-900s and breaks first under concurrency.
# Runtime override only; the tracked module is not edited.
_JUDGE_HTTP_TIMEOUT = float(os.environ.get("HALLUCI_JUDGE_TIMEOUT", "1800"))
_rrj_urlopen = rrj.request.urlopen
rrj.request.urlopen = lambda req, *a, **kw: _rrj_urlopen(
    req, *a, **{**kw, "timeout": max(kw.get("timeout") or 0, _JUDGE_HTTP_TIMEOUT)}
)


def _appworld_task_def(
    task_id: str,
    constraints: list[dict[str, str]] | None = None,
    ground_truth: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    from appworld import AppWorld

    world = AppWorld(task_id=task_id, experiment_name="requirement_probe")
    try:
        instr = world.task.instruction
    finally:
        try:
            world.close()
        except Exception:
            pass
    return {task_id: {
        "name": instr, "domain": "appworld", "difficulty": None,
        "system_constraints": constraints or [], "ground_truth_steps": ground_truth or [],
    }}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _extract_json(raw: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = raw.find("{")
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start:i + 1])
    raise ValueError("no JSON object")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--task-id", required=True)
    p.add_argument("--traj", type=Path, required=True)
    p.add_argument("--stage1", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--ground-truth", action="store_true",
                   help="ANSWER-KEY slot (recommended): inject the task's resolved test_data "
                        "outcome spec as ground_truth_steps — what required/forbidden is judged against.")
    p.add_argument("--codebook", type=Path, default=None,
                   help="EXPERIMENTAL — do NOT use for the main HAR/severity flow. Codebook "
                        "belongs in a separate pass4-style adherence audit, not in this judge's "
                        "system_constraints (see run_action_centric.py). Kept only for A/B tests.")
    p.add_argument("--verdicts", type=Path, default=None,
                   help="claim2action stage-2 verdicts jsonl. Required to compute required-miss "
                        "correctly: required_miss = required ∧ not_supported (per your "
                        "join_required_miss.py). Without it, required-miss is not reported.")
    p.add_argument("--judge-model", default="deepseek",
                   help="judge backend: gemini-pro (== your Odoo judge) | deepseek | qwen-plus")
    args = p.parse_args()

    traj_path = (args.traj if args.traj.is_absolute() else REPO / args.traj).resolve()
    stage1_path = (args.stage1 if args.stage1.is_absolute() else REPO / args.stage1).resolve()

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

    # monkeypatch the Odoo-coupled lookups
    registry = _appworld_task_def(args.task_id, constraints, ground_truth)
    bci.load_tasks_registry = lambda: registry
    bci.stage1_path_for = lambda traj_p, task_id, metadata: stage1_path
    # build_claim_items assumes the traj lives under experiments_v2/real; our AppWorld
    # trajectory doesn't, so return pilot-style metadata (stage1_path_for ignores it).
    bci.infer_real_metadata = lambda traj_p: {"condition": "pilot", "domain": None, "chain": None}

    # point the judge at the chosen backend (OpenAI-compatible ChatClient). gemini-pro
    # is the default in the pipeline (== your Odoo judge); deepseek/qwen-plus kept for A/B.
    _JUDGES = {
        "gemini-pro": ("GEMINI_PRO_API_KEY", "GEMINI_PRO_BASE_URL",
                       os.environ.get("GEMINI_PRO_MODEL_STAGE2", "@vertexai-hs3645/gemini-3.1-pro-preview")),
        "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "deepseek-chat"),
        "qwen-plus": ("QWEN_API_KEY", "QWEN_BASE_URL", "qwen-plus"),
    }
    if args.judge_model not in _JUDGES:
        raise SystemExit(f"unknown --judge-model {args.judge_model!r}; choices {list(_JUDGES)}")
    key_env, url_env, jmodel = _JUDGES[args.judge_model]
    api_key = os.environ.get(key_env, "")
    if not api_key:
        raise SystemExit(f"{key_env} not set (source research/.env)")
    default_url = "https://api.deepseek.com" if args.judge_model == "deepseek" else ""
    client = rrj.ChatClient(
        api_key=api_key,
        base_url=os.environ.get(url_env, default_url),
        model=jmodel,
    )
    print(f"requirement judge = {args.judge_model} ({jmodel})")

    items, skipped = bci.build_items([traj_path])
    print(f"built {len(items)} claim items ({len(skipped)} skipped)")

    preds: list[dict] = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for it in items:
            prompt = rrj.render_prompt(it)
            try:
                raw = client.complete(prompt, max_tokens=1200)
                obj = _extract_json(raw)
                pred = rrj.normalize_prediction(it, obj, raw=raw)
            except Exception as exc:  # noqa: BLE001
                pred = rrj.normalize_prediction(it, {}, error=str(exc))
            # did this claim have an executed tool call behind it?
            pred["_claim_type"] = it.get("claim_type") or (it.get("claim") or {}).get("type")
            preds.append(pred)
            f.write(json.dumps(pred, ensure_ascii=False) + "\n")

    # This judge's job is ONLY requirement_status. required-miss is a JOIN with
    # claim2action's not_supported verdict (required_miss = required ∧ not_supported,
    # per join_required_miss.py) — NOT "does the claim item have a tool call", which is
    # a different and wrong signal. We join here only if --verdicts is supplied.
    verdict_by_id: dict[str, str] = {}
    if args.verdicts and args.verdicts.exists():
        for v in _load_jsonl(args.verdicts):
            verdict_by_id[v["claim_id"]] = v.get("verdict")

    print("\n=== REQUIREMENT-STATUS per claim ===")
    for pr in preds:
        cid = pr.get("claim_id", "?")
        verdict = verdict_by_id.get(cid)
        flag = ""
        if verdict_by_id and pr["requirement_status"] == "required" and verdict == "not_supported":
            flag = "  <-- REQUIRED-MISS (required ∧ not_supported)"
        vshow = f" c2a={verdict}" if verdict_by_id else ""
        print(f"  {cid.split('__')[-1]:10s} {pr['requirement_status']:18s}{vshow}{flag}")
    print("\nrequirement_status:", dict(Counter(x["requirement_status"] for x in preds)))
    if verdict_by_id:
        req_miss = [x for x in preds if x["requirement_status"] == "required"
                    and verdict_by_id.get(x.get("claim_id")) == "not_supported"]
        print(f"required-miss (required ∧ not_supported): {len(req_miss)}")
    else:
        print("required-miss: not computed (pass --verdicts <claim2action verdicts> to join)")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
