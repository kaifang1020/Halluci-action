from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib import request

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parents[1]
OUT_DIR = HERE / "outputs"
PROMPT_DIR = HERE / "prompts"

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(RESEARCH / ".env", override=True)
else:
    env_path = RESEARCH / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

MODEL_REGISTRY: dict[str, dict[str, str]] = {
    "gemini-3.1-pro-preview": {
        "api_key_env": "GEMINI_PRO_API_KEY",
        "base_url_env": "GEMINI_PRO_BASE_URL",
        "model_env": "GEMINI_PRO_MODEL_STAGE3_ACTION",
        "default_model": "@vertexai-hs3645/gemini-3.1-pro-preview",
    },
}


@dataclass
class ChatClient:
    api_key: str
    base_url: str
    model: str

    def complete(self, prompt: str, *, max_tokens: int = 4000) -> str:
        base = self.base_url.rstrip("/")
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"] or ""


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


def resolve_client(model_key: str) -> ChatClient:
    cfg = MODEL_REGISTRY[model_key]
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        raise ValueError(f"Missing env var {cfg['api_key_env']}")
    base_url = os.environ.get(cfg["base_url_env"], "")
    if not base_url:
        raise ValueError(f"Missing env var {cfg['base_url_env']}")
    model = os.environ.get(cfg["model_env"], cfg["default_model"])
    return ChatClient(api_key=api_key, base_url=base_url, model=model)


def render_prompt(item: dict) -> str:
    template = (PROMPT_DIR / "action_judge_template.md").read_text(encoding="utf-8")
    rubric = (PROMPT_DIR / "requirement_rubric.md").read_text(encoding="utf-8")
    task_def = item.get("task_definition") or {}
    replacements = {
        "REQUIREMENT_RUBRIC": rubric,
        "TASK_ID": item.get("task_id"),
        "TASK_INSTRUCTION": item.get("task"),
        "CURRENT_DATETIME": item.get("current_datetime"),
        "SYSTEM_CONSTRAINTS_JSON": json.dumps(task_def.get("system_constraints") or [], ensure_ascii=False, indent=2),
        "GROUND_TRUTH_STEPS_JSON": json.dumps(task_def.get("ground_truth_steps") or [], ensure_ascii=False, indent=2),
        "ITEM_ID": item.get("item_id"),
        "TRAJ_ID": item.get("traj_id"),
        "TRAJ_KEY": item.get("traj_key"),
        "STEP_ID": item.get("step_id"),
        "ACTION_ID": item.get("action_id"),
        "TOOL_NAME": item.get("tool_name"),
        "PARAMETERS_JSON": json.dumps(item.get("parameters"), ensure_ascii=False, indent=2),
        "TOOL_RESULT_JSON": json.dumps(item.get("tool_result"), ensure_ascii=False, indent=2),
        "AUDIT_DELTA_JSON": json.dumps(item.get("audit_delta"), ensure_ascii=False, indent=2),
        "ASSISTANT_SENTENCES_JSON": json.dumps(item.get("assistant_sentences") or [], ensure_ascii=False, indent=2),
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
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start : i + 1])
    raise ValueError("Unbalanced JSON object")


def normalize_prediction(item: dict, obj: dict, raw: str | None = None, error: str | None = None) -> dict:
    status = obj.get("requirement_status")
    r = 1 if status in {"required", "allowed_supporting"} else 0
    matched = obj.get("matched_sentence_ids") or []
    said = bool(matched)
    relation = obj.get("relation") if said else "none"
    return {
        "item_id": item["item_id"],
        "traj_key": item["traj_key"],
        "action_id": item["action_id"],
        "tool_name": item["tool_name"],
        "matched_sentence_ids": matched if said else [],
        "said": said,
        "relation": relation,
        "said_reason": obj.get("said_reason", ""),
        "requirement_status": status,
        "R": r,
        "requirement_basis": obj.get("requirement_basis") or [],
        "requirement_reason": obj.get("requirement_reason", ""),
        "raw_response": raw,
        "error": error,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=Path, default=OUT_DIR / "pilot_5_action_items.jsonl")
    parser.add_argument("--out", type=Path, default=OUT_DIR / "pilot_5_judge_predictions.jsonl")
    parser.add_argument("--prompts-dir", type=Path, default=OUT_DIR / "judge_prompts")
    parser.add_argument("--model", choices=list(MODEL_REGISTRY), default="gemini-3.1-pro-preview")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--retry-errors", action="store_true",
                        help="Keep successful rows in --out, remove rows with error, and rerun only those items.")
    args = parser.parse_args()

    items = read_jsonl(args.items)
    if args.limit is not None:
        items = items[: args.limit]
    done = set()
    if args.out.exists() and args.retry_errors and not args.overwrite:
        old_rows = read_jsonl(args.out)
        keep_rows = [row for row in old_rows if not row.get("error")]
        error_ids = {row["item_id"] for row in old_rows if row.get("error")}
        args.out.unlink()
        for row in keep_rows:
            append_jsonl(args.out, row)
        done = {row["item_id"] for row in keep_rows}
        items = [item for item in items if item["item_id"] in error_ids]
    elif args.out.exists() and not args.overwrite:
        done = {row["item_id"] for row in read_jsonl(args.out)}
    if args.overwrite and args.out.exists():
        args.out.unlink()

    client = resolve_client(args.model)
    print(f"Judge model: {client.model}")
    print(f"Items: {len(items)}")

    for idx, item in enumerate(items, 1):
        if item["item_id"] in done:
            print(f"[{idx}/{len(items)}] skip {item['item_id']}")
            continue
        prompt = render_prompt(item)
        prompt_path = args.prompts_dir / f"{item['item_id']}.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        try:
            raw = client.complete(prompt, max_tokens=4000)
            obj = extract_json_object(raw)
            pred = normalize_prediction(item, obj, raw=None)
        except Exception as exc:  # noqa: BLE001
            pred = normalize_prediction(item, {}, raw=None, error=str(exc))
        append_jsonl(args.out, pred)
        print(f"[{idx}/{len(items)}] {item['item_id']}: {pred['requirement_status']} said={pred['said']} err={pred['error']}")

    print(f"Wrote predictions -> {args.out}")


if __name__ == "__main__":
    main()
