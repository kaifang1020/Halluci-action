from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PACKAGE_ROOT = Path(__file__).resolve().parent
PROMPTS_DIR = PACKAGE_ROOT / "prompts"
RUNS_DIR = PACKAGE_ROOT / "experiments" / "runs"

PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
}

PROVIDER_ALIASES = {
    "claude": "anthropic",
}

PROVIDER_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "gemini": "https://ai-gateway.apps.cloud.rt.nyu.edu/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible/v1",
    "kimi": "https://api.moonshot.cn/v1",
}


@dataclass(slots=True)
class AgentConfig:
    provider: str
    model: str
    api_key: str
    base_url: str | None = None
    temperature: float = 0.0
    max_tokens: int = 2000
    system_prompt: str = ""
    knowledge_level: str = "KL1"


@dataclass(slots=True)
class OdooConfig:
    url: str = os.getenv("ODOO_URL", "http://localhost:8069")
    db: str = os.getenv("ODOO_DB", "odoo_research")
    username: str = os.getenv("ODOO_USER", "admin")
    password: str = os.getenv("ODOO_PASSWORD", "admin")


@dataclass(slots=True)
class PostgresConfig:
    host: str = os.getenv("PGHOST", "localhost")
    port: int = int(os.getenv("PGPORT", "5432"))
    dbname: str = os.getenv("PGDATABASE", "odoo_research")
    user: str = os.getenv("PGUSER", "odoo")
    password: str = os.getenv("PGPASSWORD", "odoo_pw")


@dataclass(slots=True)
class ExperimentConfig:
    max_steps: int = int(os.getenv("HALLUCI_ACTION_MAX_STEPS", "15"))
    runs_dir: Path = RUNS_DIR


def provider_env_var(provider: str) -> str:
    normalized = normalize_provider(provider)
    if normalized not in PROVIDER_ENV_VARS:
        raise ValueError(f"Unsupported provider: {provider}")
    return PROVIDER_ENV_VARS[normalized]


def resolve_api_key(provider: str, explicit_key: str | None = None) -> str:
    if explicit_key:
        return explicit_key
    env_var = provider_env_var(provider)
    api_key = os.getenv(env_var, "")
    if not api_key:
        raise ValueError(
            f"Missing API key for provider '{provider}'. "
            f"Set {env_var} or pass --api-key."
        )
    return api_key


def default_base_url(provider: str) -> str | None:
    return PROVIDER_BASE_URLS.get(normalize_provider(provider))


def normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    return PROVIDER_ALIASES.get(normalized, normalized)


def load_system_prompt(knowledge_level: str, prompts_dir: Path | None = None) -> str:
    level = knowledge_level.strip().upper()
    prompt_path = (prompts_dir or PROMPTS_DIR) / f"system_{level}.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"System prompt not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


def build_agent_config(
    provider: str,
    model: str,
    knowledge_level: str,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 2000,
) -> AgentConfig:
    normalized_provider = normalize_provider(provider)
    return AgentConfig(
        provider=normalized_provider,
        model=model,
        api_key=resolve_api_key(normalized_provider, api_key),
        base_url=base_url if base_url is not None else default_base_url(normalized_provider),
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=load_system_prompt(knowledge_level),
        knowledge_level=knowledge_level.strip().upper(),
    )
