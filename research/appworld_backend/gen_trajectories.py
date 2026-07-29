"""Batch RAW-TRAJECTORY generator: tasks x agent models.

Produces only agent trajectories (+ audit sidecars) — no judging. Feeds the judge
runs, the HAR-by-model comparison, and the human-validation sample.

  * tools per task come from `tool_exposure.exposed_apis_for_task` (involved-app cores
    + semantic distractors) — no hand-listed EXPOSED_APIS.
  * codebook is injected (use_codebook=True), so codebook-condition behaviour is live.
  * resilient: per-cell try/except, and a cell whose trajectory already exists is SKIPPED,
    so re-running resumes instead of redoing.

Model notes (all function-calling verified):
  deepseek-chat / deepseek-reasoner  – provider "deepseek"
  qwen3-8b                            – provider "qwen" (agent sends enable_thinking=False)
  gemini-3-flash-preview              – provider "gemini". NOTE: "gemini-3.1-flash" does not
                                        exist on the gateway (3.1 is pro-only); and the
                                        provider's GOOGLE_API_KEY is invalid there, so we
                                        re-point it at GEMINI_PRO_API_KEY at runtime.
  gpt-4o-mini                         – provider "openai"

Usage:
    APPWORLD_ROOT=/Users/maokaifang/appworld-root PYTHONPATH=$PWD \
    <venv>/bin/python research/appworld_backend/gen_trajectories.py [--models a,b] [--tasks x,y]
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
RUNS = BASE / "runs"

os.environ.setdefault("APPWORLD_ROOT", "/Users/maokaifang/appworld-root")
os.environ.setdefault("HALLUCI_MAX_STEPS", "30")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# 12 write-tasks spanning the four codebook apps (so the new AZ/GM/SW rules can fire)
TASKS: list[str] = [
    # Amazon (AZ) — 099174d places a REAL order (AZ-03 no-cancel / AZ-02 card+address)
    "099174d_1", "07bb666_1",
    # Gmail (GM) — batch thread ops (GM-10 partial-failure reporting)
    "09ac073_1",
    # Splitwise (SW) — record expenses (SW-02 equal-split default) / accept invites
    "32616b5_1", "3aa1a22_1",
    # Venmo (V) — request-money family, incl. cross-app cart/order variants
    "024c982_1", "024c982_2", "2e9b91e_1", "66b7899_1", "3c13f5a_1", "22cc237_1", "92fe421_1",
]

MODELS: list[tuple[str, str]] = [
    ("deepseek", "deepseek-chat"),
    ("deepseek", "deepseek-reasoner"),
    ("qwen", "qwen3-8b"),
    ("gemini", "@vertexai-hs3645/gemini-3-flash-preview"),
    ("openai", "gpt-4o-mini"),
]


def _traj_exists(task: str, provider: str, model: str) -> Path | None:
    """A cell is done if a trajectory for this task+provider+model already exists."""
    up = task.upper().replace("_", "-")
    tag = model.split("/")[-1].replace("-", "_").replace(".", "_")
    for f in glob.glob(str(RUNS / "trajectories" / "**" / f"{up}_{provider}_*.json"), recursive=True):
        if "_archive" in f:   # archived (auth-bug / early-poc) copies must not count as done
            continue
        if tag.lower() in Path(f).stem.lower():
            return Path(f)
    return None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tasks", default=None, help="comma-separated task ids (default: built-in 12)")
    p.add_argument("--models", default=None, help="comma-separated model names to include")
    p.add_argument("--kl", default="KL1")
    p.add_argument("--max-tokens", type=int, default=4000)
    # NOTE: run_appworld_task's own default is 25 and it does NOT read HALLUCI_MAX_STEPS
    # (that env is only honoured by runner.py's __main__). A cap that bites truncates the
    # trajectory mid-task, which then reads as unfulfilled intents = fake over-claims.
    p.add_argument("--max-steps", type=int, default=40)
    args = p.parse_args()

    tasks = args.tasks.split(",") if args.tasks else TASKS
    models = [m for m in MODELS if (not args.models or m[1] in args.models.split(","))]

    from research.appworld_backend.runner import run_appworld_task
    from research.appworld_backend.tool_exposure import exposed_apis_for_task
    # research.config load_dotenv(override=True) runs at import and would clobber this,
    # so re-point the gemini provider's key AFTER the imports.
    if os.environ.get("GEMINI_PRO_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_PRO_API_KEY"]

    done, skipped, failed = 0, 0, []
    t0 = time.time()
    for task in tasks:
        try:
            exposed = exposed_apis_for_task(task)
        except Exception as e:  # noqa: BLE001
            print(f"!! {task}: tool exposure failed ({str(e)[:90]}) — skipping task")
            failed.append((task, "*", "exposure"))
            continue
        print(f"\n=== {task} — {len(exposed)} tools exposed ===")
        for provider, model in models:
            existing = _traj_exists(task, provider, model)
            if existing:
                print(f"    {provider}/{model}: reuse {existing.name}")
                skipped += 1
                continue
            try:
                print(f"    {provider}/{model}: running…", flush=True)
                run_appworld_task(task_id=task, exposed_apis=exposed, provider=provider, model=model,
                                  knowledge_level=args.kl, max_tokens=args.max_tokens,
                                  max_steps=args.max_steps, use_codebook=True)
                done += 1
            except Exception as e:  # noqa: BLE001
                print(f"    !! {provider}/{model} FAILED: {str(e)[:140]}")
                failed.append((task, model, str(e)[:80]))

    print(f"\n=== TRAJECTORIES ===  new={done}  reused={skipped}  failed={len(failed)}  "
          f"({time.time()-t0:.0f}s)")
    for t, m, e in failed:
        print(f"  !! {t} / {m}: {e}")
    print(f"  trajectories dir: {RUNS / 'trajectories'}")


if __name__ == "__main__":
    main()
