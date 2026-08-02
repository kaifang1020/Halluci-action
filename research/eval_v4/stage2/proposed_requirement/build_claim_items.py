#!/usr/bin/env python3
"""Build eval_v4 proposed-requirement claim items.

The item format is intentionally close to eval_v3-1 claim2action preprocessing:
one record per action claim, with C2A-routed evidence computed using the same
claim type and validation-scope windowing policy.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parents[2]
ROOT = RESEARCH.parent
REAL_ROOT = RESEARCH / "experiments_v2" / "real"
OUT_DIR = HERE / "outputs"
STAGE1_ROOT = RESEARCH / "eval_v3-1_claim2action" / "stage1" / "results_deepseek_chat"

ACTION_CLAIM_TYPES = {"action_intention", "action_completion"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_tasks_registry() -> dict[str, dict[str, Any]]:
    """Load research/tasks.py without importing optional runtime dependencies."""
    source = (RESEARCH / "tasks.py").read_text(encoding="utf-8")
    filtered = []
    for line in source.splitlines():
        if line.startswith("from research.config import"):
            continue
        if line.startswith("from research.tasks_legacy_6 import"):
            continue
        filtered.append(line)
    ns: dict[str, Any] = {
        "__name__": "eval_v4_proposed_requirement_tasks_loader",
        "benchmark_context_text": lambda: "",
        "LEGACY_6_TASKS": {},
    }
    exec("\n".join(filtered), ns)  # noqa: S102 - trusted local benchmark file
    return ns["TASKS"]


def sentence_split(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    return [p.strip() for p in re.split(r"(?<=[.!?。！？])\s+", text) if p.strip()]


def assistant_context(traj: dict[str, Any], step_id: int, before: int = 1) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in traj.get("steps") or []:
        sid = int(step["step_id"])
        if sid < step_id - before or sid > step_id:
            continue
        for idx, text in enumerate(sentence_split(step.get("assistant_text") or "")):
            rows.append({"sentence_id": f"S{sid}.sent{idx}", "step_id": sid, "text": text})
    return rows


def load_audit(traj: dict[str, Any], traj_path: Path) -> dict[str, Any] | None:
    audit_rel = traj.get("audit_file")
    if not audit_rel:
        return None
    audit_path = (traj_path.parent / audit_rel).resolve()
    if not audit_path.exists():
        return None
    return read_json(audit_path)


def slim_tool_calls(traj: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in traj.get("steps") or []:
        for call in step.get("tool_calls") or []:
            rows.append({
                "step_id": int(step["step_id"]),
                "call_id": call.get("call_id"),
                "tool_name": call.get("tool_name"),
                "parameters": call.get("parameters"),
            })
    return rows


def slim_tool_results(traj: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in traj.get("steps") or []:
        for result in step.get("tool_results") or []:
            rows.append({
                "step_id": int(step["step_id"]),
                "call_id": result.get("call_id"),
                "tool_name": result.get("tool_name"),
                "parameters": result.get("parameters"),
                "result": result.get("result"),
            })
    return rows


def slim_audit(audit: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rec in (audit or {}).get("records") or []:
        rows.append({
            "step_id": rec.get("step_id"),
            "action_id": rec.get("action_id"),
            "call_id": rec.get("call_id"),
            "tool_name": rec.get("tool_name"),
            "parameters": rec.get("parameters"),
            "claim_pre": rec.get("claim_pre"),
            "claim_post": rec.get("claim_post"),
        })
    return rows


def in_scope(item_step: int, claim_step: int, scope: str) -> bool:
    if scope == "same_or_following_steps":
        return item_step >= claim_step
    if scope == "same_or_previous_steps":
        return item_step <= claim_step
    if scope == "previous_steps":
        return item_step < claim_step
    if scope == "same_step":
        return item_step == claim_step
    return True


def window(items: list[dict[str, Any]], claim_step: int, scope: str) -> list[dict[str, Any]]:
    return [item for item in items if in_scope(int(item.get("step_id") or -1), claim_step, scope)]


def route_c2a_evidence(
    claim_type: str,
    validation_scope: str,
    claim_step: int,
    *,
    tool_calls: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
    audit_recs: list[dict[str, Any]],
) -> dict[str, Any]:
    if claim_type == "action_intention":
        return {
            "routing_policy": "eval_v3-1_claim2action",
            "channels": ["tool_calls"],
            "tool_calls": window(tool_calls, claim_step, validation_scope),
        }
    if claim_type == "action_completion":
        return {
            "routing_policy": "eval_v3-1_claim2action",
            "channels": ["tool_calls", "tool_results", "audit"],
            "tool_calls": window(tool_calls, claim_step, validation_scope),
            "tool_results": window(tool_results, claim_step, validation_scope),
            "audit": window(audit_recs, claim_step, validation_scope),
        }
    return {"routing_policy": "eval_v3-1_claim2action", "channels": []}


def infer_real_metadata(traj_path: Path) -> dict[str, str]:
    rel = traj_path.relative_to(REAL_ROOT)
    parts = rel.parts
    condition = parts[0]
    domain = parts[1]
    chain = "single"
    if condition == "dependent":
        chain = parts[2]
    return {"condition": condition, "domain": domain, "chain": chain}


def stage1_path_for(traj_path: Path, task_id: str, metadata: dict[str, str]) -> Path:
    if metadata["condition"] == "dependent":
        return STAGE1_ROOT / "dependent" / f"{metadata['chain']}_{task_id}_gemini-pro_v1_judge.json"
    return STAGE1_ROOT / "independent" / f"{task_id}_gemini-pro_v1_judge.json"


def traj_key_for(task_id: str, metadata: dict[str, str]) -> str:
    base = f"{task_id}_deepseek"
    if metadata["condition"] == "dependent":
        return f"{metadata['chain']}__{base}"
    return base


def discover_real_deepseek_chat() -> list[Path]:
    roots = [REAL_ROOT / "independent", REAL_ROOT / "dependent"]
    paths: list[Path] = []
    for root in roots:
        paths.extend(sorted(root.glob("**/trajectories/*_deepseek_deepseek_chat.json")))
    return sorted(paths)


def build_items(trajectories: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tasks = load_tasks_registry()
    items: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for traj_path in trajectories:
        traj = read_json(traj_path)
        task_id = traj.get("task_id") or traj_path.name.split("_", 1)[0]
        task_def = tasks.get(task_id)
        metadata = infer_real_metadata(traj_path)
        stage1_path = stage1_path_for(traj_path, task_id, metadata)
        if not task_def:
            skipped.append({"trajectory": str(traj_path.relative_to(ROOT)), "reason": "missing task definition"})
            continue
        if not stage1_path.exists():
            skipped.append({"trajectory": str(traj_path.relative_to(ROOT)), "reason": f"missing stage1: {stage1_path}"})
            continue

        stage1 = read_json(stage1_path)
        audit = load_audit(traj, traj_path)
        tool_calls = slim_tool_calls(traj)
        tool_results = slim_tool_results(traj)
        audit_recs = slim_audit(audit)
        traj_id = traj.get("trajectory_id") or traj_path.stem
        traj_key = traj_key_for(task_id, metadata)

        for step in stage1:
            step_id = int(step["step_id"])
            for idx, claim in enumerate(step.get("claims") or []):
                claim_type = claim.get("type")
                if claim_type not in ACTION_CLAIM_TYPES:
                    continue
                if not claim.get("requires_validation", False):
                    continue
                validation_scope = claim.get("validation_scope") or ""
                local_claim_id = f"S{step_id}-C{idx}"
                claim_id = f"{traj_id}__{local_claim_id}"
                items.append({
                    "schema_version": "proposed_requirement_item_v1",
                    "item_id": f"{traj_key}__{local_claim_id}",
                    "traj_key": traj_key,
                    "trajectory_path": str(traj_path.relative_to(ROOT)),
                    "stage1_path": str(stage1_path.relative_to(ROOT)),
                    "condition": metadata["condition"],
                    "domain": metadata["domain"],
                    "chain": metadata["chain"],
                    "traj_id": traj_id,
                    "task_id": task_id,
                    "task": traj.get("task"),
                    "current_datetime": (traj.get("visible_context") or {}).get("current_datetime"),
                    "task_definition": {
                        "name": task_def.get("name"),
                        "domain": task_def.get("domain"),
                        "difficulty": task_def.get("difficulty"),
                        "system_constraints": task_def.get("system_constraints") or [],
                        "ground_truth_steps": task_def.get("ground_truth_steps") or [],
                        "ambiguity_traps": task_def.get("ambiguity_traps") or [],
                    },
                    "claim_id": claim_id,
                    "local_claim_id": local_claim_id,
                    "step_id": step_id,
                    "claim_type": claim_type,
                    "validation_scope": validation_scope,
                    "claim_span": claim.get("span") or "",
                    "assistant_context": assistant_context(traj, step_id),
                    "routed_action_evidence": route_c2a_evidence(
                        claim_type,
                        validation_scope,
                        step_id,
                        tool_calls=tool_calls,
                        tool_results=tool_results,
                        audit_recs=audit_recs,
                    ),
                })

    return items, skipped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT_DIR / "real_claim_items.jsonl")
    parser.add_argument("--skipped-out", type=Path, default=OUT_DIR / "real_claim_items_skipped.jsonl")
    parser.add_argument("--limit-trajectories", type=int, default=None)
    args = parser.parse_args()

    trajectories = discover_real_deepseek_chat()
    if args.limit_trajectories is not None:
        trajectories = trajectories[: args.limit_trajectories]

    items, skipped = build_items(trajectories)
    write_jsonl(args.out, items)
    write_jsonl(args.skipped_out, skipped)

    by_condition: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for item in items:
        by_condition[item["condition"]] = by_condition.get(item["condition"], 0) + 1
        by_type[item["claim_type"]] = by_type.get(item["claim_type"], 0) + 1

    print(f"Trajectories discovered: {len(trajectories)}")
    print(f"Wrote {len(items)} claim items -> {args.out}")
    print(f"Skipped trajectories: {len(skipped)} -> {args.skipped_out}")
    print(f"By condition: {json.dumps(by_condition, ensure_ascii=False)}")
    print(f"By claim type: {json.dumps(by_type, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
