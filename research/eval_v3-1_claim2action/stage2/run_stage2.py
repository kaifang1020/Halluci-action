"""
Run the Stage 2 judge over a set of trajectories + Stage-1 claim files.

For every trajectory under the configured ind/dep dirs this script:
  1. joins it to its Stage-1 claim file,
  2. preprocesses each claim into routed evidence (reusing `preprocess.py`),
  3. renders the judge prompt (filling the `propmt_template.md` `{...}`
     variables from the Stage-1 result + trajectory),
  4. calls the chosen judge model, and
  5. writes the rendered prompts and the verdicts to disk.

Outputs, each split into dependent/ and independent/:
  - <output-root>/prompts/<split>/<stem>/<claim_id>.md   (one per claim)
  - <output-root>/<split>/<stem>_verdicts.jsonl

Join rules:
  - independent: stage1 `independent/<TASK>_..._judge.json`  <->  traj
    `<ind-dir>/<domain>/trajectories/<TASK>_<traj-suffix>.json`
  - dependent:   stage1 `dependent/<PAIR>_<TASK>_..._judge.json`  <->  traj
    `<dep-dir>/<domain>/<PAIR>/trajectories/<TASK>_<traj-suffix>.json`

Usage:
  # original deepseek_chat run (uses defaults):
  python -m research.eval_v3.stage2.run_stage2

  # deepseek_reasoner over experiments_v2/{independent,dependent}:
  python -m research.eval_v3.stage2.run_stage2 \\
      --ind-dir experiments_v2/independent \\
      --dep-dir experiments_v2/dependent \\
      --stage1-dir eval_v3/stage1/results_deepseek_reasoner \\
      --traj-suffix _deepseek_deepseek_reasoner \\
      --output-dir deepseek_reasoner
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

# --model value -> (judge.py provider, exact API model string).
MODEL_REGISTRY: dict[str, tuple[str, str]] = {
    "gemini-3.1-pro-preview": ("gemini-pro", "@vertexai-hs3645/gemini-3.1-pro-preview"),
    "deepseek-v4-pro": ("deepseek", "deepseek-v4-pro"),
}

_TASK_RE = re.compile(r"[A-Z]{1,3}-\d+")


def _task_of_traj(path: Path, traj_suffix: str) -> str:
    """`S-1_deepseek_deepseek_chat.json` -> `S-1` when suffix is `_deepseek_deepseek_chat`."""
    return path.name.replace(traj_suffix + ".json", "")


def index_trajectories(ind_dir: Path, dep_dir: Path, traj_suffix: str
                       ) -> tuple[dict[str, Path], dict[tuple[str, str], Path]]:
    """Return (independent: task_id -> path, dependent: (pair, task_id) -> path)."""
    glob = f"*{traj_suffix}.json"
    indep: dict[str, Path] = {}
    for p in ind_dir.glob(f"*/trajectories/{glob}"):
        indep[_task_of_traj(p, traj_suffix)] = p

    dep: dict[tuple[str, str], Path] = {}
    for p in dep_dir.glob(f"*/*/trajectories/{glob}"):
        pair = p.parent.parent.name          # .../<domain>/<PAIR>/trajectories/<file>
        dep[(pair, _task_of_traj(p, traj_suffix))] = p
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


def discover_jobs(split: str, stage1_dir: Path, ind_dir: Path, dep_dir: Path,
                  traj_suffix: str) -> list[dict]:
    """Build the (stage1, trajectory) work list for the requested split(s)."""
    indep_traj, dep_traj = index_trajectories(ind_dir, dep_dir, traj_suffix)
    jobs: list[dict] = []

    if split in ("all", "independent"):
        for s1 in sorted((stage1_dir / "independent").glob("*_judge.json")):
            stem = s1.stem.replace("_judge", "")
            _, task = _parse_stage1_name(stem)
            traj = indep_traj.get(task)
            if traj is None:
                print(f"  [skip] independent {task}: no trajectory found")
                continue
            jobs.append({"split": "independent", "stem": stem,
                         "task": task, "stage1": s1, "traj": traj})

    if split in ("all", "dependent"):
        for s1 in sorted((stage1_dir / "dependent").glob("*_judge.json")):
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
            fewshot: str, concurrency: int, overwrite: bool,
            prompts_dir: Path, verdicts_dir: Path) -> dict:
    split, stem = job["split"], job["stem"]
    prompt_dir = prompts_dir / split / stem
    verdict_path = verdicts_dir / split / f"{stem}_verdicts.jsonl"

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
    p.add_argument("--ind-dir", default="experiments_v2/real/independent",
                   help="Independent trajectory root (relative to research/).")
    p.add_argument("--dep-dir", default="experiments_v2/real/dependent",
                   help="Dependent trajectory root (relative to research/).")
    p.add_argument("--stage1-dir", default="eval_v3/stage1/results",
                   help="Stage-1 results dir (relative to research/).")
    p.add_argument("--traj-suffix", default="_deepseek_deepseek_chat",
                   help="Filename suffix on trajectory files (excluding .json).")
    p.add_argument("--output-dir", default="binary_results",
                   help="Output dir name under stage2/ for verdicts (prompts/ goes under it).")
    args = p.parse_args()

    provider, model = MODEL_REGISTRY[args.model]
    client, _ = _resolve_client(provider)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    guideline = GUIDELINE_PATH.read_text(encoding="utf-8")
    fewshot = FEWSHOT_PATH.read_text(encoding="utf-8")

    ind_dir = BASE / args.ind_dir
    dep_dir = BASE / args.dep_dir
    stage1_dir = BASE / args.stage1_dir
    verdicts_dir = HERE / args.output_dir
    prompts_dir = verdicts_dir / "prompts"

    jobs = discover_jobs(args.split, stage1_dir, ind_dir, dep_dir, args.traj_suffix)
    if args.limit is not None:
        jobs = jobs[: args.limit]

    print(f"Model: {args.model}  (provider={provider}, api_model={model})")
    print(f"Ind dir:  {ind_dir}")
    print(f"Dep dir:  {dep_dir}")
    print(f"Stage1:   {stage1_dir}")
    print(f"Output:   {verdicts_dir}")
    print(f"Jobs: {len(jobs)}  (split={args.split})\n")

    totals: dict[str, int] = {}
    for i, job in enumerate(jobs, 1):
        res = run_job(job, client=client, model=model, template=template,
                      guideline=guideline, fewshot=fewshot,
                      concurrency=args.concurrency, overwrite=args.overwrite,
                      prompts_dir=prompts_dir, verdicts_dir=verdicts_dir)
        for k, n in res["counts"].items():
            totals[k] = totals.get(k, 0) + n
        tag = res["status"]
        print(f"[{i}/{len(jobs)}] {job['split']}/{res['stem']}: {tag}  {res['counts']}")

    print(f"\nDone. Verdicts -> {verdicts_dir}")
    print(f"Prompts  -> {prompts_dir}")
    print(f"Verdict totals: {totals}")


if __name__ == "__main__":
    main()
