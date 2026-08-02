"""
Shared LLM configuration helpers for the Halluci-Action evaluation scripts.

The scripts use the OpenAI Python SDK interface. Providers that expose an
OpenAI-compatible API can be selected by setting both an API key and a base URL.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from openai import OpenAI


PROVIDER_PREFIXES = {
    "openai": "OPENAI",
    "gpt5-mini": "GPT5_MINI",
    "gpt-5-mini": "GPT5_MINI",
    "deepseek": "DEEPSEEK",
    "gemini": "GEMINI",
    "gemini-pro": "GEMINI_PRO",
    "gemini3.1-pro": "GEMINI_PRO",
    "gemini-flash": "GEMINI_FLASH",
    "qwen": "QWEN",
}


PASS_MODEL_ENV_KEYS = {
    "PASS1A": "LLM_MODEL_PASS1A",
    "PASS1B": "LLM_MODEL_PASS1B",
    "STAGE1": "LLM_MODEL_STAGE1",
    "STAGE2": "LLM_MODEL_STAGE2",
    "STAGE4": "LLM_MODEL_STAGE4",
}


def load_env_file(path: str | Path | None) -> None:
    """Load simple KEY=VALUE lines into os.environ without overriding existing values."""
    if not path:
        return

    env_path = Path(path).expanduser().resolve()
    if not env_path.exists():
        raise FileNotFoundError(f"env file not found: {env_path}")

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def apply_profile(profile: str | None) -> None:
    """
    Promote provider-specific env vars into generic LLM_* env vars.

    Example for profile=deepseek:
      DEEPSEEK_API_KEY -> LLM_API_KEY
      DEEPSEEK_BASE_URL -> LLM_BASE_URL
      DEEPSEEK_MODEL_STAGE2 -> LLM_MODEL_STAGE2
    """
    selected = (profile or os.environ.get("HALLUCI_LLM_PROFILE") or "").strip()
    if not selected:
        return

    prefix = PROVIDER_PREFIXES.get(selected.lower(), selected.upper().replace("-", "_"))

    provider_key = os.environ.get(f"{prefix}_API_KEY")
    provider_base_url = os.environ.get(f"{prefix}_BASE_URL")
    if provider_key:
        os.environ["LLM_API_KEY"] = provider_key
    if provider_base_url:
        os.environ["LLM_BASE_URL"] = provider_base_url

    for pass_name, generic_key in PASS_MODEL_ENV_KEYS.items():
        value = (
            os.environ.get(f"{prefix}_MODEL_{pass_name}")
            or os.environ.get(f"{prefix}_MODEL")
        )
        if value:
            os.environ[generic_key] = value


def resolve_api_key(explicit: str | None = None) -> str:
    return (
        explicit
        or os.environ.get("LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    )


def resolve_base_url(explicit: str | None = None) -> str | None:
    return (
        explicit
        or os.environ.get("LLM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or None
    )


def resolve_model(pass_name: str, explicit: str | None = None, default: str = "gpt-4o") -> str:
    env_key = PASS_MODEL_ENV_KEYS.get(pass_name.upper())
    if explicit:
        return explicit
    if env_key and os.environ.get(env_key):
        return os.environ[env_key]
    if os.environ.get("LLM_MODEL"):
        return os.environ["LLM_MODEL"]
    return default


def build_client(api_key: str | None = None, base_url: str | None = None) -> OpenAI:
    key = resolve_api_key(api_key)
    if not key:
        raise ValueError("No API key configured. Set LLM_API_KEY or provider-specific *_API_KEY.")

    kwargs: dict[str, Any] = {"api_key": key}
    resolved_base_url = resolve_base_url(base_url)
    if resolved_base_url:
        kwargs["base_url"] = resolved_base_url
    return OpenAI(**kwargs)


def configured_provider_summary() -> str:
    base_url = resolve_base_url()
    return base_url or "OpenAI default endpoint"
