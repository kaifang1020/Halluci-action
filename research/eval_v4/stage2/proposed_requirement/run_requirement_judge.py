#!/usr/bin/env python3
"""Run the eval_v4 proposed-requirement judge on claim items."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib import request


HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parents[2]
OUT_DIR = HERE / "outputs"
PROMPT_DIR = HERE / "prompts"
RUBRIC_PATH = HERE / "proposed_action_requirement_rubric.md"
TEMPLATE_PATH = PROMPT_DIR / "requirement_judge_template.md"

VALID_STATUSES = {"required", "allowed_supporting", "unnecessary", "forbidden", "unclear"}
VALID_CONFIDENCE = {"high", "medium", "low"}


try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None


def load_env() -> None:
    env_path = RESEARCH / ".env"
    if load_dotenv is not None:
        load_dotenv(env_path, override=True)
        return
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class ChatClient:
    api_key: str
    base_url: str
    model: str

    def complete(self, prompt: str, *, max_tokens: int) -> str:
        base = self.base_url.rstrip("/")
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    parts.append(str(part.get("text") or part.get("content") or ""))
                else:
                    parts.append(str(part))
            content = "\n".join(p for p in parts if p)
        if content is None:
            content = message.get("reasoning_content") or choice.get("text")
        if content is None:
            preview = json.dumps(data, ensure_ascii=False)[:1200]
            raise ValueError(f"No message content in chat response: {preview}")
        return str(content)


def resolve_client(provider: str) -> ChatClient:
    if provider != "gemini-pro":
        raise ValueError("Only provider='gemini-pro' is configured for this judge")
    api_key = (
        os.environ.get("GEMINI_PRO_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("PORTKEY_API_KEY")
        or ""
    )
    if not api_key:
        raise ValueError("Missing GEMINI_PRO_API_KEY, GEMINI_API_KEY, GOOGLE_API_KEY, or PORTKEY_API_KEY")
    base_url = (
        os.environ.get("GEMINI_PRO_BASE_URL")
        or os.environ.get("GOOGLE_BASE_URL")
        or "https://ai-gateway.apps.cloud.rt.nyu.edu/v1"
    )
    model = (
        os.environ.get("GEMINI_PRO_MODEL_PROPOSED_REQUIREMENT")
        or os.environ.get("GEMINI_PRO_MODEL_STAGE3_REQUIREMENT")
        or os.environ.get("GEMINI_PRO_MODEL_STAGE2")
        or "@vertexai-hs3645/gemini-3.1-pro-preview"
    )
    return ChatClient(api_key=api_key, base_url=base_url, model=model)


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def render_prompt(item: dict) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    rubric = RUBRIC_PATH.read_text(encoding="utf-8")
    task_def = item.get("task_definition") or {}
    constraints = task_def.get("system_constraints") or []
    replacements = {
        "REQUIREMENT_RUBRIC": rubric,
        "TASK_ID": item.get("task_id"),
        "TASK_INSTRUCTION": item.get("task"),
        "CURRENT_DATETIME": item.get("current_datetime"),
        "SYSTEM_CONSTRAINTS_JSON": json.dumps(
            [f"C-{idx}: {text}" for idx, text in enumerate(constraints, start=1)],
            ensure_ascii=False,
            indent=2,
        ),
        "GROUND_TRUTH_STEPS_JSON": json.dumps(
            [f"GT-{idx}: {text}" for idx, text in enumerate(task_def.get("ground_truth_steps") or [], start=1)],
            ensure_ascii=False,
            indent=2,
        ),
        "AMBIGUITY_TRAPS_JSON": json.dumps(task_def.get("ambiguity_traps") or [], ensure_ascii=False, indent=2),
        "ITEM_ID": item.get("item_id"),
        "TRAJ_ID": item.get("traj_id"),
        "TRAJ_KEY": item.get("traj_key"),
        "STEP_ID": item.get("step_id"),
        "CLAIM_ID": item.get("claim_id"),
        "CLAIM_TYPE": item.get("claim_type"),
        "VALIDATION_SCOPE": item.get("validation_scope"),
        "CLAIM_SPAN": item.get("claim_span"),
        "ASSISTANT_CONTEXT_JSON": json.dumps(item.get("assistant_context") or [], ensure_ascii=False, indent=2),
        "ROUTED_ACTION_EVIDENCE_JSON": json.dumps(item.get("routed_action_evidence") or {}, ensure_ascii=False, indent=2),
    }
    for key, value in replacements.items():
        template = template.replace("{" + key + "}", str(value))
    return template


def extract_json_object(raw: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    start = raw.find("{")
    if start == -1:
        raise ValueError("No JSON object found")
    depth = 0
    for idx in range(start, len(raw)):
        if raw[idx] == "{":
            depth += 1
        elif raw[idx] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start : idx + 1])
    raise ValueError("Unbalanced JSON object")


def normalize_prediction(item: dict, obj: dict, *, raw: str | None = None, error: str | None = None) -> dict:
    status = obj.get("requirement_status") if isinstance(obj, dict) else None
    confidence = obj.get("confidence") if isinstance(obj, dict) else None
    parse_error = error
    if error is None and status not in VALID_STATUSES:
        parse_error = f"Invalid requirement_status: {status!r}"
        status = "unclear"
    if error is None and confidence not in VALID_CONFIDENCE:
        confidence = "low"
    return {
        "schema_version": "proposed_requirement_prediction_v1",
        "item_id": item["item_id"],
        "claim_id": item["claim_id"],
        "traj_key": item["traj_key"],
        "task_id": item["task_id"],
        "condition": item["condition"],
        "domain": item["domain"],
        "claim_type": item["claim_type"],
        "step_id": item["step_id"],
        "requirement_status": status or "unclear",
        "basis_gt_steps": obj.get("basis_gt_steps") or [] if isinstance(obj, dict) else [],
        "basis_constraints": obj.get("basis_constraints") or [] if isinstance(obj, dict) else [],
        "reason": obj.get("reason", "") if isinstance(obj, dict) else "",
        "confidence": confidence or "low",
        "raw_response": raw,
        "error": parse_error,
    }


def select_items(items: list[dict], *, limit: int | None, shard_index: int | None, num_shards: int | None) -> list[dict]:
    if shard_index is not None or num_shards is not None:
        if shard_index is None or num_shards is None:
            raise ValueError("--shard-index and --num-shards must be provided together")
        if shard_index < 0 or shard_index >= num_shards:
            raise ValueError("--shard-index must satisfy 0 <= shard_index < num_shards")
        items = [item for idx, item in enumerate(items) if idx % num_shards == shard_index]
    if limit is not None:
        items = items[:limit]
    return items


def existing_done(out_path: Path, *, retry_errors: bool) -> set[str]:
    if not out_path.exists():
        return set()
    rows = read_jsonl(out_path)
    if not retry_errors:
        return {row["item_id"] for row in rows}
    keep = [row for row in rows if not row.get("error")]
    out_path.unlink()
    for row in keep:
        append_jsonl(out_path, row)
    return {row["item_id"] for row in keep}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=Path, default=OUT_DIR / "real_claim_items.jsonl")
    parser.add_argument("--out", type=Path, default=OUT_DIR / "real_requirement_predictions.jsonl")
    parser.add_argument("--prompts-dir", type=Path, default=OUT_DIR / "real_requirement_prompts")
    parser.add_argument("--provider", default="gemini-pro")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--num-shards", type=int, default=None)
    parser.add_argument("--shard-index", type=int, default=None)
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--condition", default=None)
    parser.add_argument("--traj-key", default=None)
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--save-raw", action="store_true")
    args = parser.parse_args()

    load_env()
    all_items = read_jsonl(args.items)
    if args.task_id:
        all_items = [item for item in all_items if item.get("task_id") == args.task_id]
    if args.condition:
        all_items = [item for item in all_items if item.get("condition") == args.condition]
    if args.traj_key:
        all_items = [item for item in all_items if item.get("traj_key") == args.traj_key]

    items = select_items(
        all_items,
        limit=args.limit,
        shard_index=args.shard_index,
        num_shards=args.num_shards,
    )

    if args.overwrite and args.out.exists():
        args.out.unlink()
    done = existing_done(args.out, retry_errors=args.retry_errors) if not args.overwrite else set()

    client = resolve_client(args.provider)
    print(f"Judge provider: {args.provider}", flush=True)
    print(f"Judge model: {client.model}", flush=True)
    print(f"Input items: {len(all_items)}; selected: {len(items)}; already done: {len(done)}", flush=True)

    for idx, item in enumerate(items, 1):
        if item["item_id"] in done:
            print(f"[{idx}/{len(items)}] skip {item['item_id']}")
            continue

        prompt = render_prompt(item)
        prompt_path = args.prompts_dir / f"{item['item_id']}.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")

        try:
            raw = client.complete(prompt, max_tokens=args.max_tokens)
            obj = extract_json_object(raw)
            pred = normalize_prediction(item, obj, raw=raw if args.save_raw else None)
        except Exception as exc:  # noqa: BLE001 - preserve per-item batch progress
            pred = normalize_prediction(item, {}, raw=None, error=str(exc))

        append_jsonl(args.out, pred)
        print(
            f"[{idx}/{len(items)}] {item['item_id']}: "
            f"{pred['requirement_status']} conf={pred['confidence']} err={pred['error']}",
            flush=True,
        )

    print(f"Wrote predictions -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
