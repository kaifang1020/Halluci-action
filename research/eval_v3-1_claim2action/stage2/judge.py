"""
Stage 2 judge: call the LLM for each preprocessed claim and parse the verdict.

Usage:
  python -m research.eval_v3.stage2.judge \
      --in research/eval_v3/stage2/outputs/C-1_deepseek_deepseek_preproc.jsonl \
      --provider deepseek \
      --out research/eval_v3/stage2/outputs/C-1_deepseek_deepseek_verdicts.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from research.eval_v3.stage2.render_prompt import (
    FEWSHOT_PATH, GUIDELINE_PATH, TEMPLATE_PATH, render_one,
)

_pkg_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_pkg_root / ".env", override=True)

# Mirror stage1/judge.py provider configs.
_PROVIDER_CONFIGS: dict[str, dict[str, str]] = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-pro",
    },
    "gemini-pro": {
        "api_key_env": "GEMINI_PRO_API_KEY",
        "base_url_env": "GEMINI_PRO_BASE_URL",
        "model_env": "GEMINI_PRO_MODEL_STAGE2",
        "default_model": "@vertexai-hs3645/gemini-3.1-pro-preview",
    },
    "gemini-flash": {
        "api_key_env": "GEMINI_FLASH_API_KEY",
        "base_url_env": "GEMINI_FLASH_BASE_URL",
        "model_env": "GEMINI_FLASH_MODEL_STAGE2",
        "default_model": "@vertexai-hs3645/gemini-3.1-flash-lite-preview",
    },
}

_VALID_VERDICTS = {"supported", "not_supported", "needs_broader_context"}


def _resolve_client(provider: str) -> tuple[OpenAI, str]:
    cfg = _PROVIDER_CONFIGS.get(provider)
    if cfg is None:
        raise ValueError(f"Unknown provider '{provider}'. Choices: {list(_PROVIDER_CONFIGS)}")
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        raise ValueError(f"Missing env var {cfg['api_key_env']} for provider '{provider}'")
    base_url = os.environ.get(cfg.get("base_url_env", ""), cfg.get("base_url", "")) or None
    model = os.environ.get(cfg.get("model_env", ""), cfg["default_model"])
    return OpenAI(api_key=api_key, base_url=base_url), model


@dataclass
class Verdict:
    claim_id: str
    verdict: str
    evidence_pointer: dict | None
    reason: str
    raw_response: str | None = None
    error: str | None = None


def _extract_json_object(raw: str) -> dict:
    """Pull the first balanced {...} object from the response."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    # Fallback: first { ... last }, greedy
    start = raw.find("{")
    if start == -1:
        raise ValueError("No '{' in response")
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start : i + 1])
    raise ValueError("Unbalanced braces in response")


def _parse_verdict(claim_id: str, raw: str) -> Verdict:
    try:
        obj = _extract_json_object(raw)
    except (ValueError, json.JSONDecodeError) as e:
        return Verdict(claim_id=claim_id, verdict="parse_error",
                       evidence_pointer=None, reason="", raw_response=raw, error=str(e))

    verdict = obj.get("verdict", "")
    if verdict not in _VALID_VERDICTS:
        return Verdict(claim_id=claim_id, verdict="parse_error",
                       evidence_pointer=obj.get("evidence_pointer"),
                       reason=obj.get("reason", ""),
                       raw_response=raw,
                       error=f"Invalid verdict value: {verdict!r}")

    return Verdict(
        claim_id=obj.get("claim_id", claim_id),
        verdict=verdict,
        evidence_pointer=obj.get("evidence_pointer"),
        reason=obj.get("reason", ""),
    )


def judge_record(record: dict, *, client: OpenAI, model: str,
                 template: str, guideline: str, fewshot: str,
                 max_tokens: int = 4000) -> Verdict:
    prompt = render_one(record, template, guideline, fewshot)
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.0,
        messages=[{"role": "user", "content": prompt}],
    )
    choice = response.choices[0]
    raw = choice.message.content or ""
    if choice.finish_reason == "length":
        return Verdict(claim_id=record["claim_id"], verdict="parse_error",
                       evidence_pointer=None, reason="",
                       raw_response=raw, error="response truncated (finish_reason=length)")
    return _parse_verdict(record["claim_id"], raw)


def run_judge(
    in_path: Path,
    *,
    provider: str = "deepseek",
    out_path: Path | None = None,
    limit: int | None = None,
    continue_on_error: bool = True,
) -> list[Verdict]:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    guideline = GUIDELINE_PATH.read_text(encoding="utf-8")
    fewshot = FEWSHOT_PATH.read_text(encoding="utf-8")

    client, model = _resolve_client(provider)
    verdicts: list[Verdict] = []

    out_file = None
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_file = out_path.open("w", encoding="utf-8")

    try:
        with in_path.open(encoding="utf-8") as f:
            for n, line in enumerate(f):
                if limit is not None and n >= limit:
                    break
                record = json.loads(line)
                try:
                    v = judge_record(record, client=client, model=model,
                                     template=template, guideline=guideline,
                                     fewshot=fewshot)
                except Exception as e:
                    if not continue_on_error:
                        raise
                    v = Verdict(claim_id=record["claim_id"], verdict="api_error",
                                evidence_pointer=None, reason="", error=str(e))
                verdicts.append(v)
                if out_file is not None:
                    out_file.write(json.dumps(asdict(v), ensure_ascii=False) + "\n")
                    out_file.flush()
                print(f"  [{n+1}] {v.claim_id}: {v.verdict}"
                      + (f"  ({v.error})" if v.error else ""))
    finally:
        if out_file is not None:
            out_file.close()

    return verdicts


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="in_path", type=Path, required=True)
    p.add_argument("--out", type=Path, default=None,
                   help="Defaults to outputs/<stem>_verdicts.jsonl alongside input.")
    p.add_argument("--provider", default="deepseek")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--stop-on-error", action="store_true",
                   help="Re-raise API/render errors instead of logging them as api_error verdicts.")
    args = p.parse_args()

    out_path = args.out
    if out_path is None:
        stem = args.in_path.stem.replace("_preproc", "")
        out_path = args.in_path.parent / f"{stem}_verdicts.jsonl"

    verdicts = run_judge(args.in_path, provider=args.provider, out_path=out_path,
                         limit=args.limit, continue_on_error=not args.stop_on_error)

    summary: dict[str, int] = {}
    for v in verdicts:
        summary[v.verdict] = summary.get(v.verdict, 0) + 1
    print(f"\nWrote {len(verdicts)} verdicts → {out_path}")
    print(f"  by verdict: {summary}")


if __name__ == "__main__":
    main()
