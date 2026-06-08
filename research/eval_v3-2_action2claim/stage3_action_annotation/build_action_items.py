from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
RESEARCH = ROOT / "research"
OUT_DIR = Path(__file__).resolve().parent / "outputs"


PILOT_TRAJECTORIES: dict[str, str] = {
    "C-1_deepseek": "experiments_v2/real/independent/crm/trajectories/C-1_deepseek_deepseek_chat.json",
    "C-5_deepseek": "experiments_v2/real/independent/crm/trajectories/C-5_deepseek_deepseek_chat.json",
    "D-5_deepseek_r02": "experiments_v2/real/independent/helpdesk/trajectories/D-5_deepseek_deepseek_chat_r02.json",
    "H-2_deepseek": "experiments_v2/real/independent/hr/trajectories/H-2_deepseek_deepseek_chat.json",
    "PR-2_deepseek": "experiments_v2/real/independent/project/trajectories/PR-2_deepseek_deepseek_chat.json",
    "D-1_deepseek": "experiments_v2/real/independent/helpdesk/trajectories/D-1_deepseek_deepseek_chat.json",
    "S-3_deepseek": "experiments_v2/real/independent/sales/trajectories/S-3_deepseek_deepseek_chat.json",
    "PR-4_deepseek": "experiments_v2/real/independent/project/trajectories/PR-4_deepseek_deepseek_chat.json",
    "S-4_deepseek": "experiments_v2/real/independent/sales/trajectories/S-4_deepseek_deepseek_chat.json",
    "P-2_deepseek": "experiments_v2/real/independent/pos/trajectories/P-2_deepseek_deepseek_chat.json",
    "PU-5_deepseek": "experiments_v2/real/independent/purchase/trajectories/PU-5_deepseek_deepseek_chat.json",
    "M-4_deepseek": "experiments_v2/real/independent/manufacturing/trajectories/M-4_deepseek_deepseek_chat.json",
    "A-2_deepseek": "experiments_v2/real/independent/accounting/trajectories/A-2_deepseek_deepseek_chat.json",
    "H-6_deepseek": "experiments_v2/real/independent/hr/trajectories/H-6_deepseek_deepseek_chat.json",
    "I-2_deepseek": "experiments_v2/real/independent/inventory/trajectories/I-2_deepseek_deepseek_chat.json",
}

STAGE1_DIR = RESEARCH / "eval_v3-1_claim2action" / "stage1" / "results_deepseek_chat" / "independent"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_tasks_registry() -> dict[str, dict]:
    """Load research/tasks.py without importing the research package.

    The package import path requires optional runtime deps that are irrelevant
    for this offline annotation builder. Executing the task definition file with
    the two project-local imports stubbed keeps this script lightweight.
    """
    source = (RESEARCH / "tasks.py").read_text(encoding="utf-8")
    filtered_lines = []
    for line in source.splitlines():
        if line.startswith("from research.config import"):
            continue
        if line.startswith("from research.tasks_legacy_6 import"):
            continue
        filtered_lines.append(line)
    ns: dict[str, Any] = {
        "__name__": "stage3_action_annotation_tasks_loader",
        "benchmark_context_text": lambda: "",
        "LEGACY_6_TASKS": {},
    }
    exec("\n".join(filtered_lines), ns)  # noqa: S102 - local trusted benchmark file
    return ns["TASKS"]


def load_audit(traj: dict, traj_path: Path) -> dict | None:
    audit_rel = traj.get("audit_file")
    if not audit_rel:
        return None
    audit_path = (traj_path.parent / audit_rel).resolve()
    if not audit_path.exists():
        return None
    return read_json(audit_path)


def load_stage1_claims(task_id: str) -> dict[int, list[dict]]:
    path = STAGE1_DIR / f"{task_id}_gemini-pro_v1_judge.json"
    if not path.exists():
        return {}
    by_step: dict[int, list[dict]] = {}
    for step in read_json(path):
        by_step[int(step["step_id"])] = step.get("claims") or []
    return by_step


def sentence_split(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    pieces = re.split(r"(?<=[.!?。！？])\s+", text)
    return [p.strip() for p in pieces if p.strip()]


def build_sentences(traj: dict) -> dict[int, list[dict]]:
    by_step: dict[int, list[dict]] = {}
    for step in traj.get("steps") or []:
        step_id = int(step["step_id"])
        sents = []
        for idx, sent in enumerate(sentence_split(step.get("assistant_text") or "")):
            sents.append({
                "sentence_id": f"S{step_id}.sent{idx}",
                "step_id": step_id,
                "text": sent,
            })
        by_step[step_id] = sents
    return by_step


def window_sentences(sentences_by_step: dict[int, list[dict]], step_id: int, window: int) -> list[dict]:
    out = []
    for sid in range(step_id - window, step_id + window + 1):
        out.extend(sentences_by_step.get(sid, []))
    return out


def all_sentences(sentences_by_step: dict[int, list[dict]]) -> list[dict]:
    out = []
    for sid in sorted(sentences_by_step):
        out.extend(sentences_by_step[sid])
    return out


def claim_groups(claims_by_step: dict[int, list[dict]], step_id: int, window: int | None) -> list[dict]:
    if window is None:
        step_ids = sorted(claims_by_step)
    else:
        step_ids = list(range(step_id - window, step_id + window + 1))
    return [
        {
            "step_id": sid,
            "claims": claims_by_step.get(sid, []),
        }
        for sid in step_ids
        if claims_by_step.get(sid)
    ]


def index_results(traj: dict) -> dict[str, dict]:
    by_call: dict[str, dict] = {}
    for step in traj.get("steps") or []:
        for result in step.get("tool_results") or []:
            call_id = result.get("call_id")
            if call_id:
                by_call[call_id] = result
    return by_call


def index_audit(audit: dict | None) -> dict[str, dict]:
    if not audit:
        return {}
    out = {}
    for rec in audit.get("records") or []:
        call_id = rec.get("call_id")
        if call_id:
            out[call_id] = {
                "action_id": rec.get("action_id"),
                "step_id": rec.get("step_id"),
                "tool_name": rec.get("tool_name"),
                "parameters": rec.get("parameters"),
                "claim_pre": rec.get("claim_pre"),
                "claim_post": rec.get("claim_post"),
            }
    return out


def is_mutation_tool(tool_name: str) -> bool:
    prefixes = (
        "create_", "update_", "delete_", "confirm_", "cancel_", "send_",
        "log_", "escalate_", "assign_", "reassign_", "close_", "apply_",
        "approve_", "reject_", "mark_", "post_", "add_",
    )
    return tool_name.startswith(prefixes)


def build_items(window: int = 1, sentence_scope: str = "all") -> list[dict]:
    items: list[dict] = []
    tasks = load_tasks_registry()
    for traj_key, rel_path in PILOT_TRAJECTORIES.items():
        traj_path = RESEARCH / rel_path
        traj = read_json(traj_path)
        audit = load_audit(traj, traj_path)
        task_id = traj.get("task_id")
        task_def = tasks[task_id]
        sentences_by_step = build_sentences(traj)
        results_by_call = index_results(traj)
        audit_by_call = index_audit(audit)
        claims_by_step = load_stage1_claims(task_id)

        for step in traj.get("steps") or []:
            step_id = int(step["step_id"])
            for idx, call in enumerate(step.get("tool_calls") or []):
                call_id = call.get("call_id") or f"step{step_id}_call{idx}"
                tool_result = results_by_call.get(call_id)
                action_id = (tool_result or {}).get("action_id") or (audit_by_call.get(call_id) or {}).get("action_id") or f"step{step_id}_action{idx}"
                item_id = f"{traj_key}__{action_id}"
                item = {
                    "item_id": item_id,
                    "traj_key": traj_key,
                    "trajectory_path": str(traj_path.relative_to(ROOT)),
                    "traj_id": traj.get("trajectory_id"),
                    "task_id": task_id,
                    "task": traj.get("task"),
                    "current_datetime": (traj.get("visible_context") or {}).get("current_datetime"),
                    "task_definition": {
                        "name": task_def.get("name"),
                        "domain": task_def.get("domain"),
                        "difficulty": task_def.get("difficulty"),
                        "system_constraints": task_def.get("system_constraints") or [],
                        "ground_truth_steps": task_def.get("ground_truth_steps") or [],
                    },
                    "step_id": step_id,
                    "action_id": action_id,
                    "call_id": call_id,
                    "tool_name": call.get("tool_name"),
                    "parameters": call.get("parameters") or {},
                    "tool_result": tool_result,
                    "audit_delta": audit_by_call.get(call_id),
                    "is_mutation": is_mutation_tool(call.get("tool_name") or ""),
                    "assistant_sentence_scope": sentence_scope,
                    "assistant_sentences": (
                        all_sentences(sentences_by_step)
                        if sentence_scope == "all"
                        else window_sentences(sentences_by_step, step_id, window)
                    ),
                    "stage1_claims_scope": sentence_scope,
                    "stage1_claims_window": claim_groups(
                        claims_by_step,
                        step_id,
                        None if sentence_scope == "all" else window,
                    ),
                }
                items.append(item)
    return items


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT_DIR / "pilot_5_action_items.jsonl")
    parser.add_argument("--window", type=int, default=1)
    parser.add_argument("--sentence-scope", choices=["all", "window"], default="all",
                        help="Use all trajectory sentences, or only +/- --window steps.")
    args = parser.parse_args()

    items = build_items(window=args.window, sentence_scope=args.sentence_scope)
    write_jsonl(args.out, items)
    by_traj: dict[str, int] = {}
    for item in items:
        by_traj[item["traj_key"]] = by_traj.get(item["traj_key"], 0) + 1
    print(f"Wrote {len(items)} action items -> {args.out}")
    print(json.dumps(by_traj, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
