"""
Run the Stage 2 judge over the full eval set (experiments_v2/real).

For every trajectory under `research/experiments_v2/real/{dependent,independent}`
this script:
  1. joins it to its Stage-1 claim file in `research/eval_v3/stage1/results`,
  2. preprocesses each claim into routed evidence (reusing `preprocess.py`),
  3. renders the judge prompt (filling the `propmt_template.md` `{...}`
     variables from the Stage-1 result + trajectory),
  4. calls the chosen judge model, and
  5. writes the rendered prompts and the verdicts to disk.

Outputs (created on demand), each split into dependent/ and independent/:
  - research/eval_v3/stage2/prompts/<split>/<stem>/<claim_id>.md   (one per claim)
  - research/eval_v3/stage2/binary_results/<split>/<stem>_verdicts.jsonl

Join rules:
  - independent: stage1 `independent/<TASK>_..._judge.json`  <->  traj
    `real/independent/<domain>/trajectories/<TASK>_deepseek_deepseek_chat.json`
  - dependent:   stage1 `dependent/<PAIR>_<TASK>_..._judge.json`  <->  traj
    `real/dependent/<domain>/<PAIR>/trajectories/<TASK>_deepseek_deepseek_chat.json`
    (the same TASK lives under multiple PAIRs as distinct trajectories, so the
    join key is (PAIR, TASK)).

Usage:
  # Full run with the default model (gemini-3.1-pro-preview):
  python -m research.eval_v3.stage2.run_stage2

  # Pick the model; restrict the split; smoke-test on a few tasks first:
  python -m research.eval_v3.stage2.run_stage2 --model deepseek-v4-pro
  python -m research.eval_v3.stage2.run_stage2 --split independent --limit 3
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from research.eval_v3.stage2.preprocess import BASE, preprocess_one
from research.eval_v3.stage2.render_prompt import (
    FEWSHOT_PATH, GUIDELINE_PATH, TEMPLATE_PATH, render_one,
)
from research.eval_v3.stage2.judge import Verdict, _resolve_client, judge_record

HERE = Path(__file__).resolve().parent
REAL = BASE / "experiments_v2/real"
STAGE1 = BASE / "eval_v3/stage1/results"
PROMPTS_DIR = HERE / "prompts"
VERDICTS_DIR = HERE / "binary_results"

# --model value -> (judge.py provider, exact API model string).
MODEL_REGISTRY: dict[str, tuple[str, str]] = {
    "gemini-3.1-pro-preview": ("gemini-pro", "@vertexai-hs3645/gemini-3.1-pro-preview"),
    "deepseek-v4-pro": ("deepseek", "deepseek-v4-pro"),
}

_TRAJ_GLOB = "*_deepseek_deepseek_chat.json"
_TASK_RE = re.compile(r"[A-Z]{1,3}-\d+")


def _task_of_traj(path: Path) -> str:
    """`S-1_deepseek_deepseek_chat.json` -> `S-1`."""
    return path.name.split("_deepseek")[0]


def index_trajectories() -> tuple[dict[str, Path], dict[tuple[str, str], Path]]:
    """Return (independent: task_id -> path, dependent: (pair, task_id) -> path).

    Globs only the canonical `dependent`/`independent` dirs, so the stray
    ' dependent' (leading-space) directory is ignored.
    """
    indep: dict[str, Path] = {}
    for p in (REAL / "independent").glob(f"*/trajectories/{_TRAJ_GLOB}"):
        indep[_task_of_traj(p)] = p

    dep: dict[tuple[str, str], Path] = {}
    for p in (REAL / "dependent").glob(f"*/*/trajectories/{_TRAJ_GLOB}"):
        pair = p.parent.parent.name          # .../<domain>/<PAIR>/trajectories/<file>
        dep[(pair, _task_of_traj(p))] = p
    return indep, dep


def _parse_stage1_name(stem: str) -> tuple[str, str]:
    """`M1_M5_M-3_gemini-pro_v1` -> (pair='M1_M5', task='M-3').
    `S-1_gemini-pro_v1` -> (pair='', task='S-1')."""
    m = _TASK_RE.search(stem)
    if not m:
        raise ValueError(f"No task id in stage1 stem {stem!r}")
    task = m.group(0)
    pair = stem[: m.start()].rstrip("_")
    return pair, task


def discover_jobs(split: str) -> list[dict]:
    """Build the (stage1, trajectory) work list for the requested split(s)."""
    indep_traj, dep_traj = index_trajectories()
    jobs: list[dict] = []

    if split in ("all", "independent"):
        for s1 in sorted((STAGE1 / "independent").glob("*_judge.json")):
            stem = s1.stem.replace("_judge", "")
            _, task = _parse_stage1_name(stem)
            traj = indep_traj.get(task)
            if traj is None:
                print(f"  [skip] independent {task}: no trajectory found")
                continue
            jobs.append({"split": "independent", "stem": stem,
                         "task": task, "stage1": s1, "traj": traj})

    if split in ("all", "dependent"):
        for s1 in sorted((STAGE1 / "dependent").glob("*_judge.json")):
            stem = s1.stem.replace("_judge", "")
            pair, task = _parse_stage1_name(stem)
            traj = dep_traj.get((pair, task))
            if traj is None:
                print(f"  [skip] dependent {pair}/{task}: no trajectory found")
                continue
            jobs.append({"split": "dependent", "stem": stem,
                         "task": task, "stage1": s1, "traj": traj})
    return jobs


def run_job(job: dict, *, client, model: str, template: str, guideline: str,
            fewshot: str, concurrency: int, overwrite: bool) -> dict:
    split, stem = job["split"], job["stem"]
    prompt_dir = PROMPTS_DIR / split / stem
    verdict_path = VERDICTS_DIR / split / f"{stem}_verdicts.jsonl"

    if verdict_path.exists() and not overwrite:
        return {"stem": stem, "status": "skipped", "counts": {}}

    records = preprocess_one(job["stage1"], job["traj"])
    prompt_dir.mkdir(parents=True, exist_ok=True)
    verdict_path.parent.mkdir(parents=True, exist_ok=True)

    # 1) Render + persist every prompt.
    rendered: list[tuple[dict, str]] = []
    for r in records:
        rd = asdict(r)
        prompt = render_one(rd, template, guideline, fewshot)
        (prompt_dir / f"{rd['claim_id']}.md").write_text(prompt, encoding="utf-8")
        rendered.append((rd, prompt))

    # 2) Judge every claim (claims within a task run concurrently).
    def _one(rd: dict) -> Verdict:
        try:
            return judge_record(rd, client=client, model=model, template=template,
                                guideline=guideline, fewshot=fewshot)
        except Exception as e:  # noqa: BLE001 - log as a verdict, keep the run going
            return Verdict(claim_id=rd["claim_id"], verdict="api_error",
                           evidence_pointer=None, reason="", error=str(e))

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        verdicts = list(ex.map(_one, [rd for rd, _ in rendered]))

    # 3) Write verdicts enriched with claim metadata (self-contained for analysis).
    counts: dict[str, int] = {}
    with verdict_path.open("w", encoding="utf-8") as f:
        for (rd, _), v in zip(rendered, verdicts):
            counts[v.verdict] = counts.get(v.verdict, 0) + 1
            row = {
                **asdict(v),
                "traj_id": rd["traj_id"],
                "step_id": rd["step_id"],
                "claim_span": rd["claim"]["span"],
                "claim_type": rd["claim"]["type"],
                "validation_scope": rd["claim"]["validation_scope"],
                "routed_channels": rd["routed_channels"],
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return {"stem": stem, "status": "done", "counts": counts}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", choices=list(MODEL_REGISTRY), default="gemini-3.1-pro-preview",
                   help="Judge model (default: gemini-3.1-pro-preview).")
    p.add_argument("--split", choices=["all", "dependent", "independent"], default="all")
    p.add_argument("--limit", type=int, default=None,
                   help="Only process the first N tasks (smoke test).")
    p.add_argument("--concurrency", type=int, default=8,
                   help="Concurrent claim-level judge calls within a task.")
    p.add_argument("--overwrite", action="store_true",
                   help="Re-run tasks whose verdict file already exists.")
    args = p.parse_args()

    provider, model = MODEL_REGISTRY[args.model]
    client, _ = _resolve_client(provider)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    guideline = GUIDELINE_PATH.read_text(encoding="utf-8")
    fewshot = FEWSHOT_PATH.read_text(encoding="utf-8")

    jobs = discover_jobs(args.split)
    if args.limit is not None:
        jobs = jobs[: args.limit]

    print(f"Model: {args.model}  (provider={provider}, api_model={model})")
    print(f"Jobs: {len(jobs)}  (split={args.split})\n")

    totals: dict[str, int] = {}
    for i, job in enumerate(jobs, 1):
        res = run_job(job, client=client, model=model, template=template,
                      guideline=guideline, fewshot=fewshot,
                      concurrency=args.concurrency, overwrite=args.overwrite)
        for k, n in res["counts"].items():
            totals[k] = totals.get(k, 0) + n
        tag = res["status"]
        print(f"[{i}/{len(jobs)}] {job['split']}/{res['stem']}: {tag}  {res['counts']}")

    print(f"\nDone. Verdicts -> {VERDICTS_DIR}")
    print(f"Prompts  -> {PROMPTS_DIR}")
    print(f"Verdict totals: {totals}")


if __name__ == "__main__":
    main()
