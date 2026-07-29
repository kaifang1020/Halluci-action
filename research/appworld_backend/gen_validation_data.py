"""Generate judge outputs for the reliability study: tasks x agent-models x judge-models.

For each (task, agent-model) trajectory it runs, per the round-1 plan:
  * stage-1 claim extraction        (deepseek, once)          -> claims
  * stage-2 fidelity verdict        (judge in FIDELITY_JUDGES) -> supported/not_supported
  * action-centric (said + req)     (judge in ACTION_JUDGES)   -> said, requirement_status

Every judge row is tagged with {task_id, agent_model, judge_model} and pooled into
two files the worksheet + agreement tools consume:
  runs/validation/pool_fidelity.jsonl   (one row per claim per fidelity judge)
  runs/validation/pool_action.jsonl     (one row per action per action judge)
plus runs/validation/manifest.json (paths per cell, for the worksheet's evidence).

Reuses the SAME baked-in fixes as run_pipeline (stage-2 v2 routing + fixed guideline).
Trajectories are reused if already on disk (newest per task+provider); otherwise the
agent is run. Additive; no edits to tracked files.

Usage:
    APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
    /Users/maokaifang/appworld-root/venv/bin/python \
        research/appworld_backend/gen_validation_data.py
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
RUNS = BASE / "runs"
VAL = RUNS / "validation"
CODEBOOK = BASE / "codebook.md"
FIXED_GUIDELINE = BASE / "stage2_guideline_appworld.md"
S1 = REPO / "research/eval_v3-1_claim2action/stage1"
S2 = REPO / "research/eval_v3-1_claim2action/stage2"

os.environ.setdefault("APPWORLD_ROOT", "/Users/maokaifang/appworld-root")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# --- study design: Venmo request-money tasks, uniform 7-tool set ---
# One toolset covers every request pattern: single-recipient (search_users+create),
# cart ("request for my cart"), order ("package was for X"), and split-among-group
# (show_contact_relationships resolves "my roommates/coworkers" -> multiple requests).
REQUEST_TOOLSET = [
    "venmo__search_users", "venmo__search_friends", "venmo__create_payment_request",
    "amazon__show_cart", "amazon__show_orders",
    "phone__search_contacts", "phone__show_contact_relationships",
]
_TASK_IDS = [
    "024c982_1", "024c982_2", "024c982_3",   # simple: public/private, friend/roommate, + note
    "2e9b91e_1", "2e9b91e_2", "2e9b91e_3",   # cart total -> request (Denise not-a-friend trap in _1)
    "66b7899_1", "66b7899_2", "66b7899_3",   # amazon order/package was for X -> request
    "22cc237_1", "22cc237_2",                # split a dinner bill among coworkers/friends
    "3c13f5a_1", "3c13f5a_2",                # split a utility bill among roommates
    "2d9f728_1",                             # split a taxi fare among roommates
    "92fe421_1",                             # shared amazon prime -> request from roommates
]
TASKS: list[tuple[str, list[str]]] = [(t, REQUEST_TOOLSET) for t in _TASK_IDS]
AGENTS: list[tuple[str, str]] = [("deepseek", "deepseek-chat"), ("qwen", "qwen3-8b")]
# (judge_model tag, how to invoke). gemini-pro is the PRIMARY judge (== your Odoo
# judge, @vertexai/gemini-3.1-pro-preview); deepseek/qwen-plus are secondary
# cheaper-alternative comparisons. qwen judge = qwen-plus (see s2 config patch below).
FIDELITY_JUDGES = [("gemini-pro", "gemini-pro"), ("deepseek", "deepseek"), ("qwen-plus", "qwen")]   # tag, stage-2 provider
ACTION_JUDGES = [("gemini-pro", "gemini-3.1-pro-preview"), ("deepseek", "deepseek"), ("qwen-plus", "qwen-plus")]  # tag, run_action_centric --model
STAGE1_PROVIDER = "gemini-pro"   # claim extraction == the real pipeline's judge


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _env():
    e = dict(os.environ)
    e["PYTHONPATH"] = str(REPO) + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    return e


def _find_traj(task: str, provider: str) -> Path | None:
    up = task.upper().replace("_", "-")
    cands = [c for c in glob.glob(str(RUNS / "trajectories" / "**" / f"{up}_{provider}_*.json"), recursive=True) if "_archive" not in c]
    return Path(max(cands, key=os.path.getmtime)) if cands else None


def _ensure_traj(task: str, exposed: list[str], provider: str, model: str) -> Path:
    existing = _find_traj(task, provider)
    if existing:
        print(f"    reuse {existing.name}")
        return existing
    print(f"    run agent {provider}/{model} on {task}")
    from research.appworld_backend.runner import run_appworld_task
    run_appworld_task(task_id=task, exposed_apis=exposed, provider=provider, model=model,
                      knowledge_level="KL1", max_tokens=4000, use_codebook=True)
    t = _find_traj(task, provider)
    if not t:
        raise SystemExit(f"agent produced no trajectory for {task}/{provider}")
    return t


def _nonempty(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0


def _read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _retry(desc: str, fn, tries: int = 4, base: float = 4.0):
    """Retry transient failures (the gemini gateway occasionally DNS/connection-errors)."""
    import time
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            wait = base * (i + 1)
            print(f"    ~ {desc} attempt {i+1}/{tries} failed: {str(e)[:110]} — retry in {wait:.0f}s")
            time.sleep(wait)
    raise last


def _subrun(cmd: list[str]) -> str:
    r = subprocess.run([str(c) for c in cmd], env=_env(), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("\n".join((r.stderr or r.stdout).splitlines()[-6:]))
    return r.stdout


def _grab(text: str, pat: str):
    import re
    m = re.search(pat, text, re.I)
    return float(m.group(1)) if m else None


def _build_pools_from_disk() -> tuple[list[dict], list[dict], list[dict]]:
    """Aggregate whatever per-cell judge files exist NOW — so a mid-run failure on one
    cell never discards the cells that already succeeded."""
    fid_tags = [t for t, _ in FIDELITY_JUDGES]
    act_tags = [t for t, _ in ACTION_JUDGES]
    fidelity_pool, action_pool, manifest = [], [], []
    for task, _ in TASKS:
        for provider, _ in AGENTS:
            cell = f"{task}__{provider}"
            fid_paths, act_paths = {}, {}
            for jm in fid_tags:
                out = VAL / f"{cell}_s2verdicts__{jm}.jsonl"
                if _nonempty(out):
                    fid_paths[jm] = str(out)
                    for v in _read_jsonl(out):
                        fidelity_pool.append({"task_id": task, "agent_model": provider, "judge_model": jm,
                                              "claim_id": v.get("claim_id"), "verdict": v.get("verdict")})
            for jm in act_tags:
                out = VAL / f"{cell}_action__{jm}.jsonl"
                if _nonempty(out):
                    act_paths[jm] = str(out)
                    for a in _read_jsonl(out):
                        action_pool.append({"task_id": task, "agent_model": provider, "judge_model": jm,
                                            "action_id": a.get("action_id"), "tool_name": a.get("tool_name"),
                                            "said": a.get("said"), "requirement_status": a.get("requirement_status")})
            traj = _find_traj(task, provider)
            manifest.append({"cell": cell, "task_id": task, "agent_model": provider,
                             "trajectory": str(traj) if traj else None,
                             "stage1": str(VAL / f"{cell}_stage1.json"), "s2preproc": str(VAL / f"{cell}_s2preproc.jsonl"),
                             "fidelity_verdicts": fid_paths, "action": act_paths})
    return fidelity_pool, action_pool, manifest


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resume", action="store_true",
                    help="keep existing per-cell files and skip recompute (resume after a failure). "
                         "Default is a CLEAN run: stale per-cell files for the configured cells are removed first.")
    a = ap.parse_args()

    VAL.mkdir(parents=True, exist_ok=True)
    if not a.resume:  # clean slate so leftovers from an earlier judge config can't corrupt the join
        for task, _ in TASKS:
            for provider, _ in AGENTS:
                for p in VAL.glob(f"{task}__{provider}_*"):
                    p.unlink()

    s1 = _load("s1judge", S1 / "judge.py")
    sys.path.insert(0, str(S2))
    import preprocess as pp  # noqa: E402
    s2 = _load("s2judge", S2 / "judge.py")
    s2.GUIDELINE_PATH = FIXED_GUIDELINE
    # qwen JUDGE = qwen-plus (non-thinking). Patch the loaded config directly rather
    # than via QWEN_MODEL_STAGE2 env — judge.py does load_dotenv(override=True) and
    # .env pins QWEN_MODEL_STAGE2=qwen3-8b, which would clobber an env override and
    # re-trigger the enable_thinking=false 400. Pointing model_env at an unset name
    # makes _resolve_client fall through to default_model=qwen-plus deterministically.
    s2._PROVIDER_CONFIGS["qwen"]["model_env"] = "QWEN_MODEL_QWENPLUS_UNSET"
    s2._PROVIDER_CONFIGS["qwen"]["default_model"] = "qwen-plus"

    failed: list[str] = []
    har_rows: list[dict] = []
    for task, exposed in TASKS:
        for provider, model in AGENTS:
            cell = f"{task}__{provider}"
            print(f"\n=== {cell} ===")
            try:
                traj = _ensure_traj(task, exposed, provider, model)

                # stage-1 claim extraction (gemini-pro, once — matches the real pipeline)
                stage1 = VAL / f"{cell}_stage1.json"
                if _nonempty(stage1):
                    print("    stage1: reuse")
                else:
                    _retry(f"{cell} stage1", lambda: s1.run_judge(
                        traj, provider=STAGE1_PROVIDER, save_output=stage1, prompt_version="v1"))

                # stage-2 preprocess once (judge-model independent), then judge per model
                preproc = VAL / f"{cell}_s2preproc.jsonl"
                recs = pp.preprocess_one(stage1, traj, codebook_path=CODEBOOK, routing_version="v2")
                pp.write_jsonl(recs, preproc)
                for jm, provider_key in FIDELITY_JUDGES:
                    out = VAL / f"{cell}_s2verdicts__{jm}.jsonl"
                    if _nonempty(out):
                        print(f"    fidelity[{jm}]: reuse")
                        continue
                    vs = _retry(f"{cell} fidelity[{jm}]",
                                lambda pk=provider_key, o=out: s2.run_judge(preproc, provider=pk, out_path=o))
                    cnt = {k: [v.verdict for v in vs].count(k) for k in {v.verdict for v in vs}}
                    print(f"    fidelity[{jm}]: {cnt}")

                # action-centric per judge model (subprocess CLI)
                for jm, model_key in ACTION_JUDGES:
                    out = VAL / f"{cell}_action__{jm}.jsonl"
                    if _nonempty(out):
                        print(f"    action[{jm}]: reuse")
                        continue

                    def _do(mk=model_key, o=out):
                        cmd = [sys.executable, str(BASE / "run_action_centric.py"), "--task-id", task,
                               "--traj", str(traj), "--stage1", str(stage1), "--out", str(o),
                               "--ground-truth", "--model", mk]
                        r = subprocess.run(cmd, env=_env(), capture_output=True, text=True)
                        if r.returncode != 0:
                            raise RuntimeError("\n".join((r.stderr or r.stdout).splitlines()[-6:]))
                        return o
                    _retry(f"{cell} action[{jm}]", _do)
                    print(f"    action[{jm}]: {len(_read_jsonl(out))} actions")

                # ---- real HAR for this cell under the gemini judge ----
                har_json = VAL / f"{cell}_har.json"
                if _nonempty(har_json):
                    print("    HAR: reuse")
                    har_rows.append(json.loads(har_json.read_text()))
                else:
                    try:
                        gver = VAL / f"{cell}_s2verdicts__gemini-pro.jsonl"
                        gact = VAL / f"{cell}_action__gemini-pro.jsonl"
                        req = VAL / f"{cell}_req__gemini.jsonl"
                        if not _nonempty(req):
                            _retry(f"{cell} requirement", lambda: _subrun([
                                sys.executable, str(BASE / "run_requirement.py"), "--task-id", task,
                                "--traj", str(traj), "--stage1", str(stage1), "--out", str(req),
                                "--ground-truth", "--verdicts", str(gver), "--judge-model", "gemini-pro"]))
                        hout = _subrun([sys.executable, str(BASE / "run_har_metrics.py"), "--task-id", task,
                                        "--traj", str(traj), "--stage1", str(stage1), "--preproc", str(preproc),
                                        "--verdicts", str(gver), "--action-centric", str(gact), "--requirement", str(req)])
                        rec = {"task_id": task, "agent_model": provider, "judge": "gemini-pro",
                               "HAR": _grab(hout, r"HAR\s*:\s*([0-9.]+)"),
                               "precision": _grab(hout, r"precision\s*:\s*([0-9.]+)"),
                               "recall": _grab(hout, r"recall\s*:\s*([0-9.]+)")}
                        har_json.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
                        har_rows.append(rec)
                        print(f"    HAR: {rec['HAR']} (prec {rec['precision']}, rec {rec['recall']})")
                    except Exception as e:  # noqa: BLE001
                        print(f"    !! HAR failed: {str(e)[:120]}")
            except Exception as e:  # noqa: BLE001
                print(f"    !! cell {cell} FAILED after retries: {str(e)[:160]}")
                failed.append(cell)

    fidelity_pool, action_pool, manifest = _build_pools_from_disk()
    (VAL / "pool_fidelity.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in fidelity_pool) + "\n", encoding="utf-8")
    (VAL / "pool_action.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in action_pool) + "\n", encoding="utf-8")
    (VAL / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # HAR summary (real HAR under the gemini judge, per task x agent)
    har_rows.sort(key=lambda r: (r["task_id"], r["agent_model"]))
    (VAL / "har_summary.json").write_text(json.dumps(har_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== POOLS ===")
    print(f"  fidelity rows: {len(fidelity_pool)}  (claims x fidelity-judges)")
    print(f"  action rows  : {len(action_pool)}  (actions x action-judges)")
    print(f"  manifest     : {VAL / 'manifest.json'}")
    print(f"\n=== HAR (gemini judge) — {len(har_rows)} cells ===")
    for r in har_rows:
        print(f"  {r['task_id']:12s} {r['agent_model']:9s}  HAR={r['HAR']}  prec={r['precision']} rec={r['recall']}")
    for am in sorted({r["agent_model"] for r in har_rows}):
        hs = [r["HAR"] for r in har_rows if r["agent_model"] == am and r["HAR"] is not None]
        if hs:
            print(f"  >> mean HAR [{am}]: {sum(hs)/len(hs):.3f}  (n={len(hs)})")
    if failed:
        print(f"  !! FAILED cells ({len(failed)}): {failed}  — re-run with --resume to fill them")


if __name__ == "__main__":
    main()
