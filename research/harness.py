from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import structlog

from research.agents import AnthropicAgent, DeepSeekAgent, GeminiAgent, KimiAgent, OpenAIAgent, QwenAgent
from research.config import (
    ExperimentConfig,
    OdooConfig,
    PostgresConfig,
    build_agent_config,
)
from research.gateway import ToolGateway
from research.tasks import TASKS, get_system_prompt, get_task, get_task_prompt, list_tasks

logger = structlog.get_logger(__name__)

PRE_CLAIM_PATTERNS = [
    re.compile(r"\b(i will|i'll|i am going to|i need to|i should|i won't|i cannot|i can't)\b", re.IGNORECASE),
]
POST_CLAIM_PATTERNS = [
    re.compile(
        r"\b(i have|i've|successfully|completed|created|updated|approved|rejected|closed|assigned|processed|cancelled|escalated)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bthe .+ has been\b", re.IGNORECASE),
]
FINAL_PATTERNS = [
    re.compile(r"\b(done|completed|finished|all set|task complete)\b", re.IGNORECASE),
]


@dataclass(slots=True)
class ToolExecutionRecord:
    call_id: str
    tool_name: str
    parameters: dict[str, Any]
    gateway_result: dict[str, Any]


@dataclass(slots=True)
class StepRecord:
    step_id: int
    assistant_text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[ToolExecutionRecord] = field(default_factory=list)
    raw_response: dict[str, Any] = field(default_factory=dict)
    claim_pre: str | None = None
    claim_post: str | None = None


@dataclass(slots=True)
class ExperimentResult:
    trajectory_id: str
    agent: str
    model: str
    task: str
    task_id: str | None
    knowledge_level: str
    steps: list[StepRecord]
    har_preliminary: dict[str, Any]


class ExperimentRunner:
    def __init__(
        self,
        experiment_config: ExperimentConfig | None = None,
        odoo_config: OdooConfig | None = None,
        postgres_config: PostgresConfig | None = None,
    ) -> None:
        self.experiment_config = experiment_config or ExperimentConfig()
        self.gateway = ToolGateway(odoo_config=odoo_config, postgres_config=postgres_config)

    def run_experiment(
        self,
        agent_name: str,
        model_name: str,
        task_prompt: str,
        knowledge_level: str,
        api_key: str | None,
        n_runs: int = 1,
        base_url: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        max_steps: int | None = None,
        task_system_prompt: str | None = None,
        task_id: str | None = None,
    ) -> ExperimentResult | list[ExperimentResult]:
        results = [
            self._run_single(
                agent_name=agent_name,
                model_name=model_name,
                task_prompt=task_prompt,
                knowledge_level=knowledge_level,
                api_key=api_key,
                base_url=base_url,
                temperature=temperature,
                max_tokens=max_tokens,
                max_steps=max_steps or self.experiment_config.max_steps,
                task_system_prompt=task_system_prompt,
                task_id=task_id,
            )
            for _ in range(n_runs)
        ]
        if n_runs == 1:
            return results[0]
        return results

    def _run_single(
        self,
        agent_name: str,
        model_name: str,
        task_prompt: str,
        knowledge_level: str,
        api_key: str | None,
        base_url: str | None,
        temperature: float,
        max_tokens: int,
        max_steps: int,
        task_system_prompt: str | None = None,
        task_id: str | None = None,
    ) -> ExperimentResult:
        config = build_agent_config(
            provider=agent_name,
            model=model_name,
            knowledge_level=knowledge_level,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # Override system prompt with task-specific one if provided
        if task_system_prompt:
            config.system_prompt = task_system_prompt
        agent = self._create_agent(config)
        trajectory_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
        messages: list[dict[str, Any]] = [{"role": "user", "content": task_prompt}]
        steps: list[StepRecord] = []
        pending_audits: list[dict[str, Any]] = []
        pending_step_index: int | None = None

        for step_id in range(1, max_steps + 1):
            response = agent.run_turn(messages)
            claim_post = extract_post_claim(response.text)
            if pending_audits and pending_step_index is not None:
                steps[pending_step_index].claim_post = claim_post
                if claim_post:
                    for audit in pending_audits:
                        self.gateway.set_claim_post(
                            step_id=audit["step_id"],
                            trajectory_id=trajectory_id,
                            audit_id=audit["audit_id"],
                            claim_post=claim_post,
                        )
            claim_pre = extract_pre_claim(response.text)
            step_record = StepRecord(
                step_id=step_id,
                assistant_text=response.text,
                tool_calls=[
                    {
                        "call_id": tool_call.call_id,
                        "tool_name": tool_call.tool_name,
                        "parameters": tool_call.parameters,
                    }
                    for tool_call in response.tool_calls
                ],
                raw_response=response.raw_response,
                claim_pre=claim_pre,
            )
            messages.append(self._assistant_message(response.text, response.tool_calls))

            current_pending_audits: list[dict[str, Any]] = []
            for tool_call in response.tool_calls:
                tool_result = self.gateway.execute(
                    tool_name=tool_call.tool_name,
                    parameters=tool_call.parameters,
                    claim_pre=claim_pre,
                    step_id=step_id,
                    trajectory_id=trajectory_id,
                )
                step_record.tool_results.append(
                    ToolExecutionRecord(
                        call_id=tool_call.call_id,
                        tool_name=tool_call.tool_name,
                        parameters=tool_call.parameters,
                        gateway_result=tool_result,
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.call_id,
                        "name": tool_call.tool_name,
                        "content": json.dumps(tool_result, ensure_ascii=False, default=str),
                    }
                )
                current_pending_audits.append({"audit_id": tool_result["audit_id"], "step_id": step_id})

            steps.append(step_record)
            pending_audits = current_pending_audits
            pending_step_index = len(steps) - 1 if current_pending_audits else None

            click.echo(
                f"[step {step_id}] text={truncate_text(response.text, 90)} "
                f"tool_calls={len(response.tool_calls)}"
            )
            if not response.tool_calls:
                break

        result = ExperimentResult(
            trajectory_id=trajectory_id,
            agent=agent_name,
            model=model_name,
            task=task_prompt,
            task_id=task_id,
            knowledge_level=knowledge_level.upper(),
            steps=steps,
            har_preliminary=build_har_preliminary(steps),
        )
        output_path = self._save_result(result)
        click.echo(f"Saved run to {output_path}")
        return result

    def _create_agent(self, config) -> Any:
        provider = config.provider.lower()
        if provider == "anthropic" or provider == "claude":
            config.provider = "anthropic"
            return AnthropicAgent(config)
        if provider == "openai":
            return OpenAIAgent(config)
        if provider == "deepseek":
            return DeepSeekAgent(config)
        if provider == "gemini":
            return GeminiAgent(config)
        if provider == "qwen":
            return QwenAgent(config)
        if provider == "kimi":
            return KimiAgent(config)
        raise ValueError(f"Unsupported agent provider: {config.provider}")

    def _assistant_message(self, text: str, tool_calls: list[Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": "assistant", "content": text}
        if tool_calls:
            payload["tool_calls"] = [
                {
                    "id": tool_call.call_id,
                    "type": "function",
                    "function": {
                        "name": tool_call.tool_name,
                        "arguments": json.dumps(tool_call.parameters, ensure_ascii=False),
                    },
                }
                for tool_call in tool_calls
            ]
        return payload

    def _save_result(self, result: ExperimentResult) -> Path:
        self.experiment_config.runs_dir.mkdir(parents=True, exist_ok=True)
        task_slug = slugify(result.task)
        output_path = self.experiment_config.runs_dir / (
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{result.agent}_{task_slug}.json"
        )
        payload = asdict(result)
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return output_path


def split_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [part.strip() for part in parts if part.strip()]


def extract_pre_claim(text: str) -> str | None:
    sentences = split_sentences(text)
    for sentence in reversed(sentences):
        if any(pattern.search(sentence) for pattern in PRE_CLAIM_PATTERNS):
            return sentence
    return None


def extract_post_claim(text: str) -> str | None:
    sentences = split_sentences(text)
    for sentence in sentences:
        if any(pattern.search(sentence) for pattern in POST_CLAIM_PATTERNS):
            return sentence
    return None


def build_har_preliminary(steps: list[StepRecord]) -> dict[str, Any]:
    tool_steps = [step for step in steps if step.tool_calls]
    tool_results = [result for step in steps for result in step.tool_results]
    error_results = [
        result
        for result in tool_results
        if result.gateway_result.get("status") == "error"
    ]
    return {
        "steps_total": len(steps),
        "tool_steps_total": len(tool_steps),
        "tool_calls_total": len(tool_results),
        "tool_errors_total": len(error_results),
        "claim_pre_coverage": round(
            sum(1 for step in tool_steps if step.claim_pre) / len(tool_steps), 3
        )
        if tool_steps
        else 0.0,
        "claim_post_coverage": round(
            sum(1 for step in tool_steps if step.claim_post) / len(tool_steps), 3
        )
        if tool_steps
        else 0.0,
    }


def truncate_text(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return slug[:48] or "task"


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ]
    )


def print_task_listing(domain: str | None = None, difficulty: str | None = None) -> None:
    """Print task registry entries in a compact, filterable format."""
    task_infos = list_tasks(domain=domain, difficulty=difficulty)
    click.echo("\nPredefined Halluci-Action Task Scenarios")
    click.echo(f"Source: research.tasks.TASKS ({len(TASKS)} total)")
    if domain or difficulty:
        click.echo(f"Filters: domain={domain or '*'}, difficulty={difficulty or '*'}")
    click.echo(f"Shown: {len(task_infos)}")
    click.echo("=" * 96)

    if not task_infos:
        click.echo("No tasks match the requested filters.")
        return

    for task_info in task_infos:
        click.echo(
            f"{task_info['id']:6s} "
            f"{task_info.get('domain', ''):15s} "
            f"{task_info.get('difficulty', ''):14s} "
            f"{task_info['name']}"
        )
        click.echo(f"       {task_info['description']}")
        click.echo(f"       Target HA types: {', '.join(task_info['target_ha_types'])}")
    click.echo("=" * 96)


@click.group()
def cli() -> None:
    configure_logging()


@cli.command()
@click.option("--agent", "agent_name", required=True, help="anthropic|openai|deepseek|qwen|kimi")
@click.option("--model", "model_name", required=True)
@click.option("--task", "task_prompt", default=None, help="Direct task prompt text")
@click.option("--task-id", default=None, help="Task ID from research.tasks.TASKS. Use 'list' to see all.")
@click.option("--kl", "knowledge_level", default="KL1", show_default=True)
@click.option("--runs", "n_runs", default=1, show_default=True, type=int)
@click.option("--api-key", default=None, help="Override provider API key.")
@click.option("--base-url", default=None, help="Override OpenAI-compatible base URL.")
@click.option("--temperature", default=0.0, show_default=True, type=float)
@click.option("--max-tokens", default=2000, show_default=True, type=int)
@click.option("--max-steps", default=15, show_default=True, type=int)
@click.option("--odoo-url", default=None)
@click.option("--odoo-db", default=None)
@click.option("--odoo-user", default=None)
@click.option("--odoo-password", default=None)
@click.option("--pg-host", default=None)
@click.option("--pg-port", default=None, type=int)
@click.option("--pg-database", default=None)
@click.option("--pg-user", default=None)
@click.option("--pg-password", default=None)
@click.option("--no-codebook", "use_codebook", is_flag=True, flag_value=False, default=True,
              help="Use per-task explicit constraints instead of the shared codebook.md.")
def run(
    agent_name: str,
    model_name: str,
    task_prompt: str | None,
    task_id: str | None,
    knowledge_level: str,
    n_runs: int,
    api_key: str | None,
    base_url: str | None,
    temperature: float,
    max_tokens: int,
    max_steps: int,
    odoo_url: str | None,
    odoo_db: str | None,
    odoo_user: str | None,
    odoo_password: str | None,
    pg_host: str | None,
    pg_port: int | None,
    pg_database: str | None,
    pg_user: str | None,
    pg_password: str | None,
    use_codebook: bool,
) -> None:
    """
    Run a Halluci-Action experiment.

    Examples:

        # Using predefined task (explicit constraints):
        python -m research.harness run --agent deepseek --model deepseek-chat --task-id S-1

        # Using codebook condition (agent must self-apply policy):
        python -m research.harness run --agent deepseek --model deepseek-chat --task-id S-1 --codebook

        # Using custom prompt:
        python -m research.harness run --agent openai --model gpt-4 --task "Process order for customer X"

        # List available tasks:
        python -m research.harness run --agent deepseek --model deepseek-chat --task-id list
    """
    # Handle task-id=list to show available tasks
    if task_id == "list":
        print_task_listing()
        return

    # Resolve task prompt and system prompt
    task_system_prompt: str | None = None
    if task_id:
        task_def = get_task(task_id)
        # User message: ONLY the task instruction (constraints never shown to agent)
        final_task_prompt = get_task_prompt(task_id, include_constraints=False)
        # System prompt: codebook condition vs explicit constraints condition
        task_system_prompt = get_system_prompt(task_id, use_codebook=use_codebook)
        click.echo(f"Constraint mode: {'codebook' if use_codebook else 'explicit'}")
        click.echo(f"\n=== Running Task: {task_def['name']} ===")
        click.echo(f"Description: {task_def['description']}")
        click.echo(f"Target HA types: {', '.join(task_def['target_ha_types'])}")
        click.echo(f"User instruction: {final_task_prompt}")
        click.echo()
    elif task_prompt:
        final_task_prompt = task_prompt
    else:
        raise click.UsageError("Either --task or --task-id must be provided.")

    default_odoo = OdooConfig()
    default_pg = PostgresConfig()
    odoo_config = OdooConfig(
        url=odoo_url or default_odoo.url,
        db=odoo_db or default_odoo.db,
        username=odoo_user or default_odoo.username,
        password=odoo_password or default_odoo.password,
    )
    postgres_config = PostgresConfig(
        host=pg_host or default_pg.host,
        port=pg_port or default_pg.port,
        dbname=pg_database or default_pg.dbname,
        user=pg_user or default_pg.user,
        password=pg_password or default_pg.password,
    )
    runner = ExperimentRunner(odoo_config=odoo_config, postgres_config=postgres_config)
    runner.run_experiment(
        agent_name=agent_name,
        model_name=model_name,
        task_prompt=final_task_prompt,
        knowledge_level=knowledge_level,
        api_key=api_key,
        n_runs=n_runs,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        max_steps=max_steps,
        task_system_prompt=task_system_prompt,
        task_id=task_id,
    )


@cli.command("list-tasks")
@click.option("--domain", default=None, help="Filter by task domain, e.g. sales or inventory.")
@click.option("--difficulty", default=None, help="Filter by difficulty: easy|medium|hard|comprehensive.")
def list_tasks_cmd(domain: str | None, difficulty: str | None) -> None:
    """List task scenarios from the reusable research.tasks registry."""
    print_task_listing(domain=domain, difficulty=difficulty)
    click.echo("\nUsage: python -m research.harness run --agent <agent> --model <model> --task-id <task_id>")
    click.echo("Example: python -m research.harness run --agent deepseek --model deepseek-chat --task-id S-1\n")


if __name__ == "__main__":
    cli()
