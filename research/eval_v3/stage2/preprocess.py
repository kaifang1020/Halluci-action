"""
Stage 2 preprocessing.

Builds one record per Stage-1 claim, routing trajectory / audit / codebook
evidence by claim_type per the routing table in `README.md`. The output is a
JSONL file that downstream rendering / judge code consumes; this module does
not call any model.

Usage:
  # Single trajectory
  python -m research.eval_v3.stage2.preprocess \
      --stage1 research/eval_v3/stage1/outputs/C-1_deepseek_deepseek_judge.json \
      --trajectory research/experiments_v2/real/independent/crm/trajectories/C-1_deepseek_deepseek_chat.json \
      --out research/eval_v3/stage2/outputs/C-1_deepseek_deepseek_preproc.jsonl

  # By annotation id (uses EVAL_SET below + defaults)
  python -m research.eval_v3.stage2.preprocess --id C-1_deepseek
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from research.tools.registry import TOOL_REGISTRY

BASE = Path(__file__).resolve().parent.parent.parent
OUTPUTS_DIR = Path(__file__).parent / "outputs"
CODEBOOK_PATH = BASE / "codebook.md"

# Mirror of stage1's EVAL_SET so --id works the same way.
EVAL_SET: dict[str, Path] = {
    "C-1_deepseek": BASE / "experiments_v2/real/independent/crm/trajectories/C-1_deepseek_deepseek_chat.json",
    "D-5_deepseek_r02": BASE / "experiments_v2/real/independent/helpdesk/trajectories/D-5_deepseek_deepseek_chat_r02.json",
    "PR-2_deepseek": BASE / "experiments_v2/real/independent/project/trajectories/PR-2_deepseek_deepseek_chat.json",
}

# claim_type → list of evidence channels (see README §Routing). For
# constraint_or_policy, the channel is further refined by validation_scope:
# "tool_registry" → tool_registry channel, otherwise → codebook.
ROUTING: dict[str, list[str]] = {
    "action_intention":     ["tool_calls"],
    "action_completion":    ["tool_calls", "tool_results", "audit"],
    "observation":          ["tool_results"],
    "constraint_or_policy": ["codebook"],  # may be overridden — see _channels_for
}


def _channels_for(claim_type: str, validation_scope: str) -> list[str]:
    if claim_type == "constraint_or_policy" and validation_scope == "tool_registry":
        return ["tool_registry"]
    return ROUTING.get(claim_type, [])


# stage1 emits {same_or_following_steps, same_or_previous_steps, previous_steps,
# codebook.md, tool_registry, —}. Only the first three are step-windowed.
def _in_scope(item_step: int, claim_step: int, scope: str) -> bool:
    if scope == "same_or_following_steps":
        return item_step >= claim_step
    if scope == "same_or_previous_steps":
        return item_step <= claim_step
    if scope == "previous_steps":
        return item_step < claim_step
    if scope == "same_step":
        return item_step == claim_step
    # Unknown / non-step scope (codebook.md, tool_registry, —): keep all.
    return True


def _window(items: list[dict], claim_step: int, scope: str) -> list[dict]:
    return [it for it in items if _in_scope(it.get("step_id", -1), claim_step, scope)]


@dataclass
class ClaimRecord:
    claim_id: str
    traj_id: str
    step_id: int
    claim: dict[str, Any]
    task_header: dict[str, Any]
    routed_channels: list[str]
    evidence: dict[str, Any] = field(default_factory=dict)


# ---------- Loaders ----------

def load_stage1(path: Path) -> list[dict]:
    """Stage1 *_judge.json: [{step_id, claims:[{span,type,requires_validation,validation_scope}]}]"""
    return json.loads(path.read_text(encoding="utf-8"))


def load_trajectory(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_audit(traj: dict, traj_path: Path) -> dict | None:
    audit_rel = traj.get("audit_file")
    if not audit_rel:
        return None
    audit_path = (traj_path.parent / audit_rel).resolve()
    if not audit_path.exists():
        return None
    return json.loads(audit_path.read_text(encoding="utf-8"))


def load_codebook(path: Path = CODEBOOK_PATH) -> str:
    return path.read_text(encoding="utf-8")


def load_tool_registry() -> str:
    """Render TOOL_REGISTRY as markdown for the judge. KL1 description
    (most informative: summary + key params + constraints) is used."""
    lines: list[str] = ["# Tool Registry", ""]
    for spec in TOOL_REGISTRY:
        params = spec.parameters or {}
        required = params.get("required") or []
        props = params.get("properties") or {}
        lines.append(f"## `{spec.name}` ({spec.domain})")
        lines.append(spec.description("KL1"))
        lines.append("")
        lines.append("**Parameters:**")
        for pname, pschema in props.items():
            mark = " *(required)*" if pname in required else ""
            ptype = pschema.get("type", "")
            pdesc = pschema.get("description", "")
            enum = pschema.get("enum")
            enum_part = f" enum={enum}" if enum else ""
            lines.append(f"- `{pname}` ({ptype}){mark}{enum_part}: {pdesc}")
        if spec.constraints:
            lines.append("")
            lines.append("**Constraints:**")
            for c in spec.constraints:
                lines.append(f"- {c}")
        lines.append("")
    return "\n".join(lines)


# ---------- Slim views (drop redundant fields per README §Evidence Channels) ----------

def slim_tool_calls(traj: dict) -> list[dict]:
    out = []
    for step in traj["steps"]:
        for tc in step.get("tool_calls") or []:
            out.append({
                "step_id": step["step_id"],
                "call_id": tc.get("call_id"),
                "tool_name": tc.get("tool_name"),
                "parameters": tc.get("parameters"),
            })
    return out


def slim_tool_results(traj: dict) -> list[dict]:
    out = []
    for step in traj["steps"]:
        for tr in step.get("tool_results") or []:
            out.append({
                "step_id": step["step_id"],
                "call_id": tr.get("call_id"),
                "tool_name": tr.get("tool_name"),
                "parameters": tr.get("parameters"),
                "result": tr.get("result"),
            })
    return out


def slim_audit(audit: dict | None) -> list[dict]:
    """Keep only the state-delta fields. gateway_result duplicates tool_results."""
    if not audit:
        return []
    out = []
    for rec in audit.get("records") or []:
        out.append({
            "step_id": rec.get("step_id"),
            "action_id": rec.get("action_id"),
            "call_id": rec.get("call_id"),
            "tool_name": rec.get("tool_name"),
            "claim_pre": rec.get("claim_pre"),
            "claim_post": rec.get("claim_post"),
        })
    return out


# ---------- Routing ----------

def build_task_header(traj: dict) -> dict[str, Any]:
    vis = traj.get("visible_context") or {}
    return {
        "task_id": traj.get("task_id"),
        "task": traj.get("task"),
        "current_datetime": vis.get("current_datetime"),
    }


def route_evidence(
    claim_type: str,
    validation_scope: str,
    claim_step: int,
    *,
    tool_calls: list[dict],
    tool_results: list[dict],
    audit_recs: list[dict],
    codebook: str,
    tool_registry: str,
) -> tuple[list[str], dict[str, Any]]:
    channels = _channels_for(claim_type, validation_scope)
    payload: dict[str, Any] = {}
    for ch in channels:
        if ch == "tool_calls":
            payload["tool_calls"] = _window(tool_calls, claim_step, validation_scope)
        elif ch == "tool_results":
            payload["tool_results"] = _window(tool_results, claim_step, validation_scope)
        elif ch == "audit":
            payload["audit"] = _window(audit_recs, claim_step, validation_scope)
        elif ch == "codebook":
            payload["codebook"] = codebook
        elif ch == "tool_registry":
            payload["tool_registry"] = tool_registry
    return channels, payload


# ---------- Driver ----------

def preprocess_one(
    stage1_path: Path,
    traj_path: Path,
    *,
    codebook_path: Path = CODEBOOK_PATH,
) -> list[ClaimRecord]:
    stage1 = load_stage1(stage1_path)
    traj = load_trajectory(traj_path)
    audit = load_audit(traj, traj_path)

    task_header = build_task_header(traj)
    tool_calls = slim_tool_calls(traj)
    tool_results = slim_tool_results(traj)
    audit_recs = slim_audit(audit)
    codebook = load_codebook(codebook_path)
    tool_registry = load_tool_registry()

    traj_id = traj.get("trajectory_id") or traj_path.stem
    records: list[ClaimRecord] = []

    for step in stage1:
        step_id = int(step["step_id"])
        for idx, c in enumerate(step.get("claims") or []):
            if not c.get("requires_validation", False):
                continue
            ctype = c.get("type", "")
            if ctype not in ROUTING:
                # Type does not map to any routable channel — skip and surface
                # via a sentinel record so callers can audit Stage-1 typing.
                continue

            vscope = c.get("validation_scope", "")
            channels, evidence = route_evidence(
                ctype,
                vscope,
                step_id,
                tool_calls=tool_calls,
                tool_results=tool_results,
                audit_recs=audit_recs,
                codebook=codebook,
                tool_registry=tool_registry,
            )
            records.append(
                ClaimRecord(
                    claim_id=f"{traj_id}__S{step_id}-C{idx}",
                    traj_id=traj_id,
                    step_id=step_id,
                    claim={
                        "span": c.get("span", ""),
                        "type": ctype,
                        "validation_scope": c.get("validation_scope", ""),
                    },
                    task_header=task_header,
                    routed_channels=channels,
                    evidence=evidence,
                )
            )

    return records


def write_jsonl(records: list[ClaimRecord], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


def _resolve_traj_for_id(ann_id: str, override: Path | None) -> Path:
    if override is not None:
        return override
    if ann_id not in EVAL_SET:
        raise ValueError(f"--id {ann_id!r} not in EVAL_SET and no --trajectory override")
    return EVAL_SET[ann_id]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--id", default=None,
                   help="Annotation id from EVAL_SET (e.g. C-1_deepseek). Used to derive defaults.")
    p.add_argument("--stage1", type=Path, default=None,
                   help="Stage1 *_judge.json. If absent and --id is set, derives from stage1 outputs dir.")
    p.add_argument("--trajectory", type=Path, default=None,
                   help="Trajectory JSON. If absent and --id is set, derives from EVAL_SET.")
    p.add_argument("--codebook", type=Path, default=CODEBOOK_PATH)
    p.add_argument("--out", type=Path, default=None,
                   help="Output JSONL. Defaults to outputs/<stage1-stem>_preproc.jsonl.")
    p.add_argument("--provider", default="deepseek",
                   help="Used only to derive default --stage1 path from --id.")
    args = p.parse_args()

    if args.stage1 is None:
        if args.id is None:
            p.error("Provide --stage1 or --id")
        args.stage1 = (BASE / "eval_v3/stage1/outputs"
                       / f"{args.id}_{args.provider}_judge.json")

    traj_path = _resolve_traj_for_id(args.id, args.trajectory) if args.id else args.trajectory
    if traj_path is None:
        p.error("Provide --trajectory or --id with an EVAL_SET entry")

    out_path = args.out or (OUTPUTS_DIR / f"{args.stage1.stem.replace('_judge', '')}_preproc.jsonl")

    records = preprocess_one(args.stage1, traj_path, codebook_path=args.codebook)
    write_jsonl(records, out_path)

    by_type: dict[str, int] = {}
    for r in records:
        by_type[r.claim["type"]] = by_type.get(r.claim["type"], 0) + 1
    print(f"Wrote {len(records)} records → {out_path}")
    print(f"  by type: {by_type}")


if __name__ == "__main__":
    main()
