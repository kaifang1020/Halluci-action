"""End-to-end Halluci-Action pipeline on ONE AppWorld task — one command.

Mirrors the Odoo Halluci-Action pipeline stage-for-stage, reusing the SAME judge
modules (eval_v3-1 claim2action, eval_v3-2 action2claim), so the two are aligned:

    agent run              (in-process tool-calling on AppWorld)  -> trajectory + audit
    stage-1 claim2action   (eval_v3-1/stage1/judge.py)            -> claims
    stage-2 fidelity        (eval_v3-1/stage2, v2 routing + fixed  -> supported / not_supported
                             guideline BAKED IN here)
    action-centric answer-key (eval_v3-2, --ground-truth)         -> said + requirement (WHAT axis)
    action-centric codebook   (eval_v3-2, --codebook)             -> forbidden           (HOW/policy axis)
    requirement answer-key    (eval_v3-2, --ground-truth)         -> per-claim proposed requirement
    HAR metrics                                                    -> HAR / precision / recall
    two-axis UI (make_pipeline_ui2.py)                            -> pipeline_<task>_<tag>.html

Alignment conventions (same as the established Odoo design):
  * requirement / action judges are scored against the ANSWER KEY (test_data via
    ground_truth_util), NOT the codebook.
  * the codebook is a SEPARATE policy pass (pass4-style), shown on its own axis.

Baked-in fixes (so you never re-apply them by hand):
  * stage-2 routing_version = "v2"  (routes tool_results + claim_context for intents)
  * stage-2 guideline = appworld_backend/stage2_guideline_appworld.md
    (speech-act fulfilment + confirmation-deferral rules)
  * agent max_tokens defaults to 4000 (2000 truncated summaries)

Additive: no edits to any tracked file. Reuses the appworld_backend CLIs
(run_action_centric.py / run_requirement.py / run_har_metrics.py) via subprocess.

Usage (from the halluci repo root, in the AppWorld venv):
    APPWORLD_ROOT=/Users/maokaifang/appworld-root \
    /Users/maokaifang/appworld-root/venv/bin/python \
        research/appworld_backend/run_pipeline.py \
        --task-id 692c77d_1 --provider deepseek --model deepseek-chat

    # re-run only the judge chain on an existing trajectory (skip the agent):
    ... run_pipeline.py --task-id 2e9b91e_1 \
        --traj research/appworld_backend/runs/trajectories/2E9B91E-1_deepseek_deepseek_chat_r02.json \
        --exposed-apis amazon__show_cart,venmo__search_users,venmo__search_friends,venmo__create_payment_request
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
RUNS = BASE / "runs"
CODEBOOK = BASE / "codebook.md"
FIXED_GUIDELINE = BASE / "stage2_guideline_appworld.md"
S1 = REPO / "research/eval_v3-1_claim2action/stage1"
S2 = REPO / "research/eval_v3-1_claim2action/stage2"

os.environ.setdefault("APPWORLD_ROOT", "/Users/maokaifang/appworld-root")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))  # so `from research.appworld_backend...` works w/o PYTHONPATH


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


# Judge modules build their OpenAI client with no explicit timeout, so the SDK default
# (600s) applies. A single judged cell routinely runs 500-900s (one hit 2600s), so as soon
# as cells are judged concurrently the queued calls blow past 600s and die with
# APITimeoutError -- that is what killed 56/60 cells in an earlier 4-worker batch, and it
# was misread at the time as "the gateway serialises requests". A 2-vs-1 probe against the
# NYU gateway measured a clean 2.00x speedup (20.6 -> 41.3 req/min), i.e. it concurrs fine.
# Widen the client timeout (and let the SDK retry) so concurrency is actually usable.
# Runtime override only -- the tracked judge.py is never edited.
JUDGE_CLIENT_TIMEOUT = float(os.environ.get("HALLUCI_JUDGE_TIMEOUT", "1800"))
JUDGE_CLIENT_RETRIES = int(os.environ.get("HALLUCI_JUDGE_RETRIES", "4"))


def _patch_client_timeout(mod) -> None:
    """Wrap a judge module's `_resolve_client` so its OpenAI client gets a long timeout."""
    orig = getattr(mod, "_resolve_client", None)
    if orig is None or getattr(mod, "_timeout_patched", False):
        return

    def resolve(provider: str):
        client, model = orig(provider)
        try:  # .with_options returns a copy carrying the new settings
            client = client.with_options(timeout=JUDGE_CLIENT_TIMEOUT,
                                         max_retries=JUDGE_CLIENT_RETRIES)
        except Exception:  # noqa: BLE001 - never let the tuning break the run
            pass
        return client, model

    mod._resolve_client = resolve
    mod._timeout_patched = True


def _run(cmd, desc):
    print(f"    $ {' '.join(str(c) for c in cmd[-4:])}")
    r = subprocess.run([str(c) for c in cmd], env=_env(), capture_output=True, text=True)
    if r.returncode != 0:
        print(f"    !! {desc} FAILED (exit {r.returncode})")
        print("    " + "\n    ".join((r.stderr or r.stdout or "").splitlines()[-12:]))
        raise SystemExit(1)
    return r.stdout


def _derive_apis(task_id: str) -> list[str] | None:
    """required_apis (train/dev) -> exposed set; else union of existing trajectories."""
    from appworld import AppWorld
    try:
        w = AppWorld(task_id=task_id, experiment_name="derive_apis", ground_truth_mode="full")
        reqs = sorted(getattr(w.task.ground_truth, "required_apis", []) or [])
        w.close()
        if reqs:
            skip = {"supervisor.show_account_passwords", "supervisor.show_profile"}
            return [r.replace(".", "__") for r in reqs if not r.endswith(".login") and r not in skip]
    except Exception:
        pass
    up = task_id.upper().replace("_", "-")
    seen: set[str] = set()
    for f in glob.glob(str(RUNS / "trajectories" / "**" / f"{up}_*.json"), recursive=True):
        if "_archive" in f:
            continue
        tj = json.loads(Path(f).read_text())
        for s in tj.get("steps", []):
            for tc in (s.get("tool_calls") or []):
                seen.add(tc["tool_name"])
    return sorted(seen) or None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--task-id", required=True)
    p.add_argument("--provider", default="deepseek")
    p.add_argument("--model", default="deepseek-chat")
    p.add_argument("--exposed-apis", default=None,
                   help="comma-separated app__api; 'auto' = systematic tool_exposure (involved-app "
                        "cores + semantic distractors); auto-derived from required_apis/trajectories if omitted")
    p.add_argument("--tool-ratio", type=float, default=1 / 3, help="distractor:real ratio for --exposed-apis auto")
    p.add_argument("--tool-random", action="store_true",
                   help="random cross-app distractors instead of semantic bias (with --exposed-apis auto)")
    p.add_argument("--max-tokens", type=int, default=4000)
    p.add_argument("--kl", default="KL1")
    p.add_argument("--no-codebook", action="store_true", help="run the no-codebook baseline")
    p.add_argument("--traj", type=Path, default=None, help="reuse this trajectory; skip the agent step")
    p.add_argument("--tag", default=None, help="output filename tag (default: provider_model)")
    p.add_argument("--judge", default="gemini-pro",
                   help="JUDGE model for stage1/stage2/action/requirement (== your Odoo judge). "
                        "stage1/stage2 provider name; mapped to the action/requirement model key.")
    args = p.parse_args()

    task = args.task_id
    tag = args.tag or f"{args.provider}_{args.model}".replace("-", "").replace(".", "")
    use_codebook = not args.no_codebook
    py = sys.executable
    judge = args.judge
    # stage1/stage2 use the provider NAME; action/requirement CLIs use a model KEY.
    judge_model = {"gemini-pro": "gemini-3.1-pro-preview", "gemini-flash": "gemini-3.1-flash-preview",
                   "deepseek": "deepseek", "qwen-plus": "qwen-plus"}.get(judge, judge)
    RUNS.mkdir(parents=True, exist_ok=True)
    print(f"\n=== PIPELINE  task={task}  model={args.provider}/{args.model}  codebook={use_codebook} ===\n")

    # ---------- 1. AGENT ----------
    if args.traj:
        traj = args.traj if args.traj.is_absolute() else REPO / args.traj
        print(f"[1/8] AGENT   reuse {traj.name}")
    else:
        print("[1/8] AGENT   run in-process (tool-calling, codebook injected)")
        from research.appworld_backend.runner import run_appworld_task
        if args.exposed_apis == "auto":
            from research.appworld_backend.tool_exposure import exposed_apis_for_task
            exposed = exposed_apis_for_task(task, ratio=args.tool_ratio, semantic=not args.tool_random)
            print(f"        exposed: auto-toolset ({len(exposed)} tools = involved-app cores + "
                  f"{'random' if args.tool_random else 'semantic'} distractors @ ratio {args.tool_ratio:.2f})")
        else:
            exposed = (args.exposed_apis.split(",") if args.exposed_apis else _derive_apis(task))
        if not exposed:
            raise SystemExit(f"cannot derive EXPOSED_APIS for {task}; pass --exposed-apis")
        print(f"        exposed: {exposed}")
        run_appworld_task(task_id=task, exposed_apis=exposed, provider=args.provider, model=args.model,
                          knowledge_level=args.kl, max_tokens=args.max_tokens, use_codebook=use_codebook)
        up = task.upper().replace("_", "-")
        cands = [c for c in glob.glob(str(RUNS / "trajectories" / "**" / f"{up}_*.json"), recursive=True) if "_archive" not in c]
        traj = Path(max(cands, key=os.path.getmtime))
        print(f"        -> {traj.name}")

    # ---------- 2. STAGE 1 (claim2action) ----------
    print(f"[2/8] STAGE1  extract claims  (judge={judge})")
    s1 = _load("s1judge", S1 / "judge.py")
    _patch_client_timeout(s1)
    stage1 = RUNS / f"stage1_{task}_{tag}.json"
    s1.run_judge(traj, provider=judge, save_output=stage1, prompt_version="v1")
    print(f"        -> {stage1.name}")

    # ---------- 3. STAGE 2 (fidelity: v2 routing + fixed guideline) ----------
    print("[3/8] STAGE2  fidelity  (v2 routing + fixed guideline BAKED IN)")
    sys.path.insert(0, str(S2))
    import preprocess as pp  # noqa: E402
    s2 = _load("s2judge", S2 / "judge.py")
    _patch_client_timeout(s2)
    s2.GUIDELINE_PATH = FIXED_GUIDELINE
    recs = pp.preprocess_one(stage1, traj, codebook_path=CODEBOOK, routing_version="v2")
    c2a_preproc = RUNS / f"stage2_{task}_{tag}_preproc.jsonl"
    pp.write_jsonl(recs, c2a_preproc)
    c2a_verdicts = RUNS / f"stage2_{task}_{tag}_verdicts.jsonl"
    vs = s2.run_judge(c2a_preproc, provider=judge, out_path=c2a_verdicts)
    fid = Counter(v.verdict for v in vs)
    prec = fid.get("supported", 0) / (sum(fid.values()) or 1)
    print(f"        {dict(fid)}  C2A precision={prec:.3f}")

    # ---------- 4. ACTION-CENTRIC (answer key) ----------
    print("[4/8] ACTION  answer-key (requirement / WHAT axis)")
    ac_gt = RUNS / f"ac_{task}_{tag}_gt.jsonl"
    _run([py, BASE / "run_action_centric.py", "--task-id", task, "--traj", traj,
          "--stage1", stage1, "--out", ac_gt, "--ground-truth", "--model", judge_model], "action-centric gt")

    # ---------- 5. ACTION-CENTRIC (codebook, policy) ----------
    ac_cb = None
    if use_codebook:
        print("[5/8] ACTION  codebook (policy / HOW axis)")
        ac_cb = RUNS / f"ac_{task}_{tag}_cb.jsonl"
        _run([py, BASE / "run_action_centric.py", "--task-id", task, "--traj", traj,
              "--stage1", stage1, "--out", ac_cb, "--codebook", CODEBOOK, "--model", judge_model], "action-centric cb")
    else:
        print("[5/8] ACTION  (skipped — no codebook)")

    # ---------- 6. REQUIREMENT (answer key, per claim) ----------
    print("[6/8] REQMT   per-claim proposed requirement (answer-key)")
    req_gt = RUNS / f"req_{task}_{tag}_gt.jsonl"
    _run([py, BASE / "run_requirement.py", "--task-id", task, "--traj", traj, "--stage1", stage1,
          "--out", req_gt, "--ground-truth", "--verdicts", c2a_verdicts, "--judge-model", judge], "requirement gt")

    # ---------- 7. HAR ----------
    print("[7/8] HAR     metrics")
    har_out = _run([py, BASE / "run_har_metrics.py", "--task-id", task, "--traj", traj, "--stage1", stage1,
                    "--preproc", c2a_preproc, "--verdicts", c2a_verdicts,
                    "--action-centric", ac_gt, "--requirement", req_gt], "har")
    def _grab(pat):
        m = re.search(pat, har_out, re.I)
        return float(m.group(1)) if m else None
    har = _grab(r"HAR\s*:\s*([0-9.]+)")
    hprec = _grab(r"precision\s*:\s*([0-9.]+)")
    hrec = _grab(r"recall\s*:\s*([0-9.]+)")
    hoc = _grab(r"over-claims\s*:\s*([0-9]+)")      # bipartite counts, kept for UI consistency
    hsil = _grab(r"silent actions\s*:\s*([0-9]+)")
    if hprec is None:
        hprec = round(prec, 3)
    print(f"        HAR={har} precision={hprec} recall={hrec} over-claims={hoc} silent={hsil}")

    # ---------- 8. UI ----------
    print("[8/8] UI      two-axis")
    ui = RUNS / f"pipeline_{task}_{tag}.html"
    cmd = [py, BASE / "make_pipeline_ui2.py", "--task-id", task, "--trajectory", traj,
           "--c2a-preproc", c2a_preproc, "--c2a-verdicts", c2a_verdicts, "--requirement", req_gt,
           "--action-centric", ac_gt, "--out", ui]
    if ac_cb:
        cmd += ["--action-centric-policy", ac_cb, "--policy-source", "codebook.md"]
    if har is not None:
        cmd += ["--har", har]
    if hprec is not None:
        cmd += ["--precision", hprec]
    if hrec is not None:
        cmd += ["--recall", hrec]
    if hoc is not None:
        cmd += ["--over-claims", str(int(hoc))]
    if hsil is not None:
        cmd += ["--silent", str(int(hsil))]
    _run(cmd, "ui")

    print(f"\n=== DONE ===\n  UI: {ui}\n  fidelity: {dict(fid)} (C2A precision {prec:.3f})")
    if ac_cb:
        pol = [json.loads(l) for l in ac_cb.read_text().splitlines() if l.strip()]
        forb = [a for a in pol if a.get("requirement_status") == "forbidden"]
        cov = [a for a in forb if a.get("said") is False]
        print(f"  policy:   {len(forb)} forbidden ({len(cov)} covert)")


if __name__ == "__main__":
    main()
