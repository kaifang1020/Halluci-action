"""Run the formal Gemini bidirectional audit for one adapted Tau2 trajectory."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from dotenv import load_dotenv

from .adapter import adapt_tau2_run, select_tau2_run
from .build_gemini_audit_report import write_report
from .generate_demo_audit_html import generate_report


HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parents[1]
ROOT = RESEARCH.parent
DEFAULT_RESULTS = (
    ROOT
    / "tau2-bench"
    / "data"
    / "tau2"
    / "results"
    / "final"
    / "claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json"
)
DEFAULT_OUT_DIR = HERE / "outputs" / "airline_task3"
DEFAULT_REPORT_DATA = HERE / "fixtures" / "airline_task3_demo_audit.json"
DEFAULT_REPORT_HTML = HERE / "airline_task3_demo_audit.html"
DEFAULT_MODEL = "@vertexai-hs3645/gemini-3.1-pro-preview"
SOURCE_URL = (
    "https://github.com/sierra-research/tau2-bench/blob/main/data/tau2/results/final/"
    "claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json"
)
ACTION_CLAIM_TYPES = {"action_intention", "action_completion"}


def load_module(name: str, path: Path, *, import_dir: Path | None = None) -> ModuleType:
    if import_dir is not None and str(import_dir) not in sys.path:
        sys.path.insert(0, str(import_dir))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def configure_gemini(model: str) -> tuple[str, str, str]:
    load_dotenv(RESEARCH / ".env", override=True)
    api_key = (
        os.environ.get("GEMINI_PRO_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("PORTKEY_API_KEY")
        or ""
    )
    if not api_key:
        raise ValueError(
            "Missing GEMINI_PRO_API_KEY, GEMINI_API_KEY, GOOGLE_API_KEY, or PORTKEY_API_KEY"
        )
    base_url = (
        os.environ.get("GEMINI_PRO_BASE_URL")
        or os.environ.get("GOOGLE_BASE_URL")
        or os.environ.get("PORTKEY_BASE_URL")
        or "https://ai-gateway.apps.cloud.rt.nyu.edu/v1"
    )
    os.environ["GEMINI_PRO_API_KEY"] = api_key
    os.environ["GEMINI_PRO_BASE_URL"] = base_url
    for env_name in (
        "GEMINI_PRO_MODEL_STAGE1",
        "GEMINI_PRO_MODEL_STAGE2",
        "GEMINI_PRO_MODEL_STAGE3_ACTION",
        "GEMINI_PRO_MODEL_PROPOSED_REQUIREMENT",
    ):
        os.environ[env_name] = model
    return api_key, base_url, model


def visible_user_dialogue(trajectory: dict[str, Any]) -> str:
    rows = [
        f"turn {event['turn_idx']}: {event.get('content') or ''}"
        for event in trajectory.get("events") or []
        if event.get("role") == "user"
    ]
    return f"Initial request: {trajectory['task']}\n\nVisible user dialogue:\n" + "\n".join(rows)


def reference_steps(trajectory: dict[str, Any]) -> list[str]:
    reference = (
        (trajectory.get("evaluator_context") or {})
        .get("reference_solution", {})
        .get("actions", [])
    )
    return [
        f"{action.get('name')}({json.dumps(action.get('arguments') or {}, ensure_ascii=False, sort_keys=True)})"
        for action in reference
    ]


def sentence_split(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return []
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?。！？])\s+", normalized)
        if part.strip()
    ]


def build_sentences(trajectory: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for step in trajectory.get("steps") or []:
        for index, text in enumerate(sentence_split(step.get("assistant_text") or "")):
            rows.append(
                {
                    "sentence_id": f"S{step['step_id']}.sent{index}",
                    "step_id": step["step_id"],
                    "text": text,
                }
            )
    return rows


def build_action_items(
    trajectory: dict[str, Any], stage1: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    sentences = build_sentences(trajectory)
    claims_by_step = {int(row["step_id"]): row.get("claims") or [] for row in stage1}
    task_text = visible_user_dialogue(trajectory)
    task_definition = {
        "name": "Tau2 Airline Task 3",
        "domain": (trajectory.get("source") or {}).get("domain"),
        "difficulty": None,
        "system_constraints": [(trajectory.get("agent_context") or {}).get("policy") or ""],
        "ground_truth_steps": reference_steps(trajectory),
    }
    items = []
    for step in trajectory.get("steps") or []:
        results = {
            row["call_id"]: row for row in step.get("tool_results") or []
        }
        for index, call in enumerate(step.get("tool_calls") or []):
            result = results.get(call["call_id"])
            action_id = (result or {}).get("action_id") or f"S{step['step_id']}-A{index}"
            items.append(
                {
                    "item_id": f"tau2_task3__{action_id}",
                    "traj_key": "tau2_airline_task3_trial0",
                    "trajectory_path": "canonical_trajectory.json",
                    "condition": "tau_llm_simulator",
                    "domain": "airline",
                    "chain": "multi_turn",
                    "traj_id": trajectory["trajectory_id"],
                    "task_id": trajectory["task_id"],
                    "task": task_text,
                    "current_datetime": "2024-05-15 15:00:00 EST",
                    "task_definition": task_definition,
                    "step_id": step["step_id"],
                    "action_id": action_id,
                    "call_id": call["call_id"],
                    "tool_name": call["tool_name"],
                    "parameters": call.get("parameters") or {},
                    "tool_result": result,
                    "audit_delta": None,
                    "is_mutation": False,
                    "assistant_sentence_scope": "all",
                    "assistant_sentences": sentences,
                    "stage1_claims_scope": "all",
                    "stage1_claims_window": [
                        {"step_id": step_id, "claims": claims}
                        for step_id, claims in claims_by_step.items()
                        if claims
                    ],
                }
            )
    return items


def build_requirement_items(
    trajectory: dict[str, Any], c2a_items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    task_definition = {
        "system_constraints": [(trajectory.get("agent_context") or {}).get("policy") or ""],
        "ground_truth_steps": reference_steps(trajectory),
        "ambiguity_traps": [],
    }
    steps = {int(step["step_id"]): step for step in trajectory.get("steps") or []}
    items = []
    for record in c2a_items:
        step_id = int(record["step_id"])
        context = [
            {
                "step_id": nearby,
                "text": (steps.get(nearby) or {}).get("assistant_text", ""),
            }
            for nearby in range(max(1, step_id - 1), step_id + 1)
            if nearby in steps
        ]
        items.append(
            {
                "schema_version": "proposed_requirement_item_v1",
                "item_id": record["claim_id"],
                "claim_id": record["claim_id"],
                "traj_key": "tau2_airline_task3_trial0",
                "task_id": trajectory["task_id"],
                "condition": "tau_llm_simulator",
                "domain": "airline",
                "claim_type": record["claim"]["type"],
                "step_id": step_id,
                "validation_scope": record["claim"]["validation_scope"],
                "claim_span": record["claim"]["span"],
                "task": visible_user_dialogue(trajectory),
                "current_datetime": "2024-05-15 15:00:00 EST",
                "task_definition": task_definition,
                "assistant_context": context,
                "routed_action_evidence": record["evidence"],
            }
        )
    return items


def call_json_with_retry(
    client: Any,
    prompt: str,
    extract_json: Any,
    *,
    max_tokens: int,
    attempts: int = 2,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for _attempt in range(attempts):
        try:
            return extract_json(client.complete(prompt, max_tokens=max_tokens))
        except Exception as exc:  # noqa: BLE001 - retry malformed hosted output
            last_error = exc
    assert last_error is not None
    raise last_error


def run_pipeline(
    results_path: Path,
    output_dir: Path,
    report_data: Path,
    report_html: Path,
    *,
    task_id: str,
    trial: int,
    model: str,
    overwrite: bool,
) -> dict[str, Any]:
    _api_key, _base_url, resolved_model = configure_gemini(model)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    simulation, task = select_tau2_run(payload, task_id=task_id, trial=trial)
    trajectory_model = adapt_tau2_run(payload, simulation, task)
    trajectory = trajectory_model.model_dump(exclude_none=True)
    canonical_path = output_dir / "canonical_trajectory.json"
    canonical_path.write_text(
        json.dumps(trajectory, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    stage1_dir = RESEARCH / "eval_v3-1_claim2action" / "stage1"
    stage1_mod = load_module(
        "tau2_stage1_judge", stage1_dir / "judge.py", import_dir=stage1_dir
    )
    stage1_path = output_dir / "stage1_claims.json"
    if overwrite or not stage1_path.exists():
        stage1_mod.run_judge(
            canonical_path,
            provider="gemini-pro",
            save_output=stage1_path,
            prompt_version="v1",
        )

    stage2_dir = RESEARCH / "eval_v3-1_claim2action" / "stage2"
    preprocess_mod = load_module(
        "tau2_stage2_preprocess", stage2_dir / "preprocess.py", import_dir=stage2_dir
    )
    c2a_judge_mod = load_module(
        "tau2_stage2_judge", stage2_dir / "judge.py", import_dir=stage2_dir
    )
    render_mod = sys.modules["render_prompt"]
    records = preprocess_mod.preprocess_one(
        stage1_path, canonical_path, routing_version="v1"
    )
    records = [
        record for record in records if record.claim["type"] in ACTION_CLAIM_TYPES
    ]
    c2a_items_path = output_dir / "stage2_c2a_items.jsonl"
    write_jsonl(c2a_items_path, [asdict(record) for record in records])
    c2a_prompt_dir = output_dir / "prompts" / "c2a"
    c2a_prompt_dir.mkdir(parents=True, exist_ok=True)
    template = render_mod.TEMPLATE_PATH.read_text(encoding="utf-8")
    guideline = render_mod.GUIDELINE_PATH.read_text(encoding="utf-8")
    fewshot = render_mod.FEWSHOT_PATH.read_text(encoding="utf-8")
    for record in [asdict(row) for row in records]:
        prompt = render_mod.render_one(record, template, guideline, fewshot)
        (c2a_prompt_dir / f"{record['claim_id'].split('__')[-1]}.md").write_text(
            prompt, encoding="utf-8"
        )
    c2a_predictions_path = output_dir / "stage2_c2a_verdicts.jsonl"
    if overwrite or not c2a_predictions_path.exists():
        c2a_judge_mod.run_judge(
            c2a_items_path,
            provider="gemini-pro",
            out_path=c2a_predictions_path,
            continue_on_error=False,
        )

    action_dir = (
        RESEARCH
        / "eval_v3-2_action2claim"
        / "stage3_action_annotation"
    )
    action_mod = load_module(
        "tau2_action_judge", action_dir / "run_action_judge.py", import_dir=action_dir
    )
    client = action_mod.ChatClient(
        api_key=os.environ["GEMINI_PRO_API_KEY"],
        base_url=os.environ["GEMINI_PRO_BASE_URL"],
        model=resolved_model,
    )
    stage1 = json.loads(stage1_path.read_text(encoding="utf-8"))
    action_items = build_action_items(trajectory, stage1)
    action_items_path = output_dir / "stage3_a2c_items.jsonl"
    write_jsonl(action_items_path, action_items)
    action_predictions_path = output_dir / "stage3_a2c_predictions.jsonl"
    action_prompt_dir = output_dir / "prompts" / "a2c"
    action_prompt_dir.mkdir(parents=True, exist_ok=True)
    if overwrite or not action_predictions_path.exists():
        predictions = []
        for item in action_items:
            prompt = action_mod.render_prompt(item)
            (action_prompt_dir / f"{item['item_id']}.md").write_text(
                prompt, encoding="utf-8"
            )
            obj = call_json_with_retry(
                client, prompt, action_mod.extract_json_object, max_tokens=4000
            )
            predictions.append(action_mod.normalize_prediction(item, obj, raw=None))
        write_jsonl(action_predictions_path, predictions)

    requirement_dir = RESEARCH / "eval_v4" / "stage2" / "proposed_requirement"
    requirement_mod = load_module(
        "tau2_requirement_judge",
        requirement_dir / "run_requirement_judge.py",
        import_dir=requirement_dir,
    )
    requirement_items = build_requirement_items(
        trajectory, read_jsonl(c2a_items_path)
    )
    requirement_items_path = output_dir / "severity_claim_items.jsonl"
    write_jsonl(requirement_items_path, requirement_items)
    requirement_predictions_path = output_dir / "severity_claim_predictions.jsonl"
    requirement_prompt_dir = output_dir / "prompts" / "severity_claim"
    requirement_prompt_dir.mkdir(parents=True, exist_ok=True)
    if overwrite or not requirement_predictions_path.exists():
        predictions = []
        for index, item in enumerate(requirement_items, start=1):
            prompt = requirement_mod.render_prompt(item)
            prompt_path = requirement_prompt_dir / (
                f"{index}_{item['claim_id'].split('__')[-1]}.md"
            )
            prompt_path.write_text(prompt, encoding="utf-8")
            try:
                obj = call_json_with_retry(
                    client, prompt, requirement_mod.extract_json_object, max_tokens=2400
                )
                prediction = requirement_mod.normalize_prediction(item, obj, raw=None)
            except Exception as exc:  # noqa: BLE001 - preserve auditable error row
                prediction = requirement_mod.normalize_prediction(
                    item, {}, raw=None, error=str(exc)
                )
            predictions.append(prediction)
        write_jsonl(requirement_predictions_path, predictions)

    old_manifest = None
    manifest_path = output_dir / "run_manifest.json"
    if manifest_path.exists() and not overwrite:
        old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = {
        "schema_version": "halluci_action_tau2_judge_manifest_v1",
        "run_at": (old_manifest or {}).get("run_at")
        or datetime.now(timezone.utc).isoformat(),
        "source_path": str(results_path),
        "source_url": SOURCE_URL,
        "task_id": task_id,
        "trial": trial,
        "judge_provider": "gemini-pro",
        "judge_model": resolved_model,
        "temperature": 0.0,
        "prompt_versions": {
            "stage1": "eval_v3-1/system_v1",
            "c2a": "eval_v3-1/stage2",
            "a2c": "eval_v3-2/action_judge_template",
            "severity": "eval_v4/proposed_requirement",
        },
        "artifact_files": {
            "canonical": canonical_path.name,
            "stage1": stage1_path.name,
            "c2a_items": c2a_items_path.name,
            "c2a_verdicts": c2a_predictions_path.name,
            "a2c_items": action_items_path.name,
            "a2c_verdicts": action_predictions_path.name,
            "severity_items": requirement_items_path.name,
            "severity_verdicts": requirement_predictions_path.name,
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    report = write_report(output_dir, report_data, source_path=results_path)
    generate_report(report_data, report_html)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--task-id", default="3")
    parser.add_argument("--trial", type=int, default=0)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-data", type=Path, default=DEFAULT_REPORT_DATA)
    parser.add_argument("--report-html", type=Path, default=DEFAULT_REPORT_HTML)
    parser.add_argument(
        "--overwrite", action="store_true", help="Re-run all paid judge calls."
    )
    args = parser.parse_args()
    report = run_pipeline(
        args.results,
        args.output_dir,
        args.report_data,
        args.report_html,
        task_id=args.task_id,
        trial=args.trial,
        model=args.model,
        overwrite=args.overwrite,
    )
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
    print(f"Wrote report: {args.report_html}")


if __name__ == "__main__":
    main()
