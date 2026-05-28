from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

_pkg_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_pkg_root / ".env", override=True)

# Supported providers and how to resolve their config from env vars
_PROVIDER_CONFIGS: dict[str, dict[str, str]] = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
    },
    "gemini-pro": {
        "api_key_env": "GEMINI_PRO_API_KEY",
        "base_url_env": "GEMINI_PRO_BASE_URL",
        "model_env": "GEMINI_PRO_MODEL_STAGE1",
        "default_model": "@vertexai/gemini-3.1-pro-preview",
    },
    "gemini-flash": {
        "api_key_env": "GEMINI_FLASH_API_KEY",
        "base_url_env": "GEMINI_FLASH_BASE_URL",
        "model_env": "GEMINI_FLASH_MODEL_STAGE1",
        "default_model": "@vertexai/gemini-2.0-flash",
    },
}


def _resolve_client(provider: str) -> tuple[OpenAI, str]:
    """Return (OpenAI client, model_name) for the given provider."""
    cfg = _PROVIDER_CONFIGS.get(provider)
    if cfg is None:
        raise ValueError(f"Unknown provider '{provider}'. Choices: {list(_PROVIDER_CONFIGS)}")

    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        raise ValueError(f"Missing env var {cfg['api_key_env']} for provider '{provider}'")

    base_url = os.environ.get(cfg.get("base_url_env", ""), cfg.get("base_url", "")) or None
    model = os.environ.get(cfg.get("model_env", ""), cfg["default_model"])

    client = OpenAI(api_key=api_key, base_url=base_url)
    return client, model

REQUIRES_VALIDATION: dict[str, bool] = {
    "action_intention": True,
    "action_completion": True,
    "observation": True,
    "constraint_or_policy": True,
    "recommendation": False,
    "reasoning_conclusion": False,
    "non_actionable_text": False,
}

VALIDATION_SCOPE: dict[str, str] = {
    "action_intention": "same_or_following_steps",
    "action_completion": "same_or_previous_steps",
    "observation": "previous_steps",
    "recommendation": "—",
    "reasoning_conclusion": "—",
    "non_actionable_text": "—",
}


@dataclass
class JudgeClaim:
    span: str
    type: str
    requires_validation: bool
    validation_scope: str


@dataclass
class JudgeStep:
    step_id: int
    claims: list[JudgeClaim] = field(default_factory=list)


def _load_prompt(name: str, version: str | None = None) -> str:
    if version is not None:
        stem, suffix = name.rsplit(".", 1)
        versioned = f"{stem}_{version}.{suffix}"
        versioned_path = Path(__file__).parent / "prompts" / versioned
        if versioned_path.exists():
            return versioned_path.read_text(encoding="utf-8")
    return (Path(__file__).parent / "prompts" / name).read_text(encoding="utf-8")


def extract_assistant_texts(traj_path: Path) -> list[tuple[int, str]]:
    """Return [(step_id, assistant_text), ...] for all steps with non-empty text."""
    data = json.loads(traj_path.read_text(encoding="utf-8"))
    result = []
    for step in data["steps"]:
        text = step.get("assistant_text", "").strip()
        result.append((step["step_id"], text))
    return result


def _build_user_message(steps: list[tuple[int, str]], fewshot: str) -> str:
    numbered = "\n\n".join(
        f"Step {sid}: {text}" if text else f"Step {sid}: [no assistant text]"
        for sid, text in steps
    )
    return (
        fewshot
        + "\n\n---\n\nNow annotate the following trajectory:\n\n"
        + numbered
    )


def _parse_response(raw: str) -> list[JudgeStep]:
    # Extract the first JSON array from the response
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON array found in judge response:\n{raw[:500]}")

    data = json.loads(match.group(0))
    judge_steps = []

    for step_data in data:
        step_id = int(step_data["step_id"])
        claims = []
        for c in step_data.get("claims", []):
            ctype = c.get("type", "")
            source = c.get("source")

            if ctype == "constraint_or_policy" and source in ("codebook.md", "tool_registry"):
                validation_scope = source
            else:
                validation_scope = VALIDATION_SCOPE.get(ctype, "—")

            claims.append(
                JudgeClaim(
                    span=c.get("span", ""),
                    type=ctype,
                    requires_validation=REQUIRES_VALIDATION.get(ctype, False),
                    validation_scope=validation_scope,
                )
            )
        judge_steps.append(JudgeStep(step_id=step_id, claims=claims))

    return judge_steps


def run_judge(
    traj_path: Path,
    provider: str = "deepseek",
    save_output: Path | None = None,
    prompt_version: str | None = None,
) -> list[JudgeStep]:
    steps = extract_assistant_texts(traj_path)
    system = _load_prompt("system.md", version=prompt_version)
    fewshot = _load_prompt("fewshot.md", version=prompt_version)
    user_msg = _build_user_message(steps, fewshot)

    client, model = _resolve_client(provider)
    response = client.chat.completions.create(
        model=model,
        max_tokens=32000,
        temperature=0.0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    )

    choice = response.choices[0]
    raw = choice.message.content
    if choice.finish_reason == "length":
        print(f"  WARNING: response truncated (finish_reason=length). Output may be incomplete.")
        if raw is None:
            raise ValueError("Response was truncated and content is None (gateway returned no partial content). Try increasing max_tokens or chunking the trajectory.")
    if raw is None:
        raise ValueError("Response content is None.")
    judge_steps = _parse_response(raw)

    if save_output:
        save_output.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "step_id": js.step_id,
                "claims": [
                    {
                        "span": c.span,
                        "type": c.type,
                        "requires_validation": c.requires_validation,
                        "validation_scope": c.validation_scope,
                    }
                    for c in js.claims
                ],
            }
            for js in judge_steps
        ]
        save_output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    return judge_steps


def load_judge_output(path: Path) -> list[JudgeStep]:
    data = json.loads(path.read_text(encoding="utf-8"))
    steps = []
    for s in data:
        claims = [
            JudgeClaim(
                span=c["span"],
                type=c["type"],
                requires_validation=c["requires_validation"],
                validation_scope=c["validation_scope"],
            )
            for c in s.get("claims", [])
        ]
        steps.append(JudgeStep(step_id=s["step_id"], claims=claims))
    return steps
