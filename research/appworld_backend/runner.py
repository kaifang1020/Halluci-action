"""Integrated AppWorld backend for the REAL Halluci-Action runner.

PURELY ADDITIVE: this file does NOT modify any existing halluci-action source. It
subclasses ``research.harness.ExperimentRunner`` and REUSES its real
``_run_single`` / ``run_experiment`` / ``_create_agent`` / ``_save_result`` (your
actual loop, claim capture, StepRecord assembly, split_audit_payload). It only:

  * swaps the backend gateway   (Odoo ``ToolGateway`` -> ``AppWorldGateway``),
  * injects AppWorld tool schemas via runtime rebinding (no agent-file edits),
  * corrects the recorded context clock to AppWorld's per-task datetime.

Your Odoo pipeline stays byte-for-byte unchanged; run it exactly as before.

Run this smoke driver (in the AppWorld venv) with:
    PYTHONPATH=<halluci-repo> HALLUCI_PROVIDER=deepseek HALLUCI_MODEL=deepseek-chat \
    HALLUCI_MAX_STEPS=25 APPWORLD_ROOT=/Users/maokaifang/appworld-root \
    /Users/maokaifang/appworld-root/venv/bin/python research/appworld_backend/runner.py
"""

from __future__ import annotations

import os

# path_store reads APPWORLD_ROOT at ``import appworld`` time; set a default (an already
# exported value still wins via setdefault).
os.environ.setdefault("APPWORLD_ROOT", "/Users/maokaifang/appworld-root")

from pathlib import Path
from typing import Any

from research.appworld_backend.gateway import AppWorldGateway
from research.config import ExperimentConfig
from research.harness import ExperimentRunner
from research.appworld_backend.poc import build_system_prompt  # reuse the neutral AppWorld prompt
from research.appworld_backend.tools import AppWorldToolExecutor

DEFAULT_RUNS_DIR = Path(__file__).resolve().parent / "runs"
DEFAULT_CODEBOOK_PATH = Path(__file__).resolve().parent / "codebook.md"


class AppWorldExperimentRunner(ExperimentRunner):
    """``ExperimentRunner`` whose backend is an in-process AppWorld world.

    Reuses the parent's real ``_run_single`` / ``run_experiment``. Deliberately does
    NOT call ``super().__init__`` (which constructs the Odoo/Postgres ``ToolGateway``).
    """

    def __init__(
        self,
        world: Any,
        exposed_apis: list[str],
        constraints: dict[str, tuple[str, ...]] | None = None,
        experiment_config: ExperimentConfig | None = None,
    ) -> None:
        self.experiment_config = experiment_config or ExperimentConfig(runs_dir=DEFAULT_RUNS_DIR)
        self.world = world
        self.executor = AppWorldToolExecutor(world, exposed_apis, constraints=constraints or {})
        self.gateway = AppWorldGateway(world, self.executor)
        self._install_appworld_tool_schemas()

    def _install_appworld_tool_schemas(self) -> None:
        """Inject OUR AppWorld tool schemas into the reused agents WITHOUT editing agent
        files: rebind the module-level ``get_openai_tools`` / ``get_anthropic_tools`` they
        call at ``run_turn`` (each agent imported the name into its own module namespace,
        so we rebind it in each module).
        """
        import research.agents.claude_agent as _ca
        import research.agents.deepseek_agent as _ds
        import research.agents.openai_agent as _oa

        build = self.executor.build_tool_schemas
        _oa.get_openai_tools = lambda kl: build(kl, provider="openai")
        _ds.get_openai_tools = lambda kl: build(kl, provider="openai")
        _ca.get_anthropic_tools = lambda kl: build(kl, provider="anthropic")

    def _save_result(self, result: Any) -> Any:
        """Correct the recorded context to AppWorld's per-task datetime, then delegate to
        the REAL ``_save_result`` (split_audit_payload).

        The parent stamps ``visible_context`` / ``audit_context`` with the Odoo global
        benchmark clock (``benchmark_now()``). The agent already saw the right "now" via
        the system prompt; this only fixes the saved metadata. No edits to harness.py.
        """
        dt = self.world.task.datetime
        ctx = {
            "current_datetime": dt.isoformat(),
            "timezone": str(getattr(dt, "tzinfo", "") or "UTC"),
        }
        result.visible_context = dict(ctx)
        result.audit_context = dict(ctx)
        return super()._save_result(result)


def run_appworld_task(
    task_id: str,
    exposed_apis: list[str],
    provider: str = "deepseek",
    model: str = "deepseek-chat",
    knowledge_level: str = "KL1",
    max_steps: int = 25,
    temperature: float = 0.0,
    max_tokens: int = 2000,
    constraints: dict[str, tuple[str, ...]] | None = None,
    experiment_name: str = "halluci_action_appworld",
    use_codebook: bool = False,
    codebook_path: Path = DEFAULT_CODEBOOK_PATH,
) -> Any:
    """Run ONE AppWorld task through the REAL Halluci-Action runner and save it.

    Returns the ``ExperimentResult`` (already written to ``runs_appworld/`` by the
    reused ``_save_result``). NEVER calls ``world.evaluate()``.

    ``use_codebook``: if True, the policy codebook at ``codebook_path`` (default
    ``research/appworld_backend/codebook.md``) is injected verbatim into the agent's
    system prompt (the "codebook condition"). If False, the agent runs with no standing
    policy (the "no-codebook" baseline).
    """
    from appworld import AppWorld

    from research.config import default_base_url, normalize_provider, resolve_api_key

    prov = normalize_provider(provider)
    codebook_text = codebook_path.read_text(encoding="utf-8") if use_codebook else None
    world = AppWorld(task_id=task_id, experiment_name=experiment_name)
    try:
        runner = AppWorldExperimentRunner(world, exposed_apis, constraints=constraints)
        result = runner.run_experiment(
            agent_name=prov,
            model_name=model,
            task_prompt=world.task.instruction,
            knowledge_level=knowledge_level,
            api_key=resolve_api_key(prov),
            base_url=default_base_url(prov),
            temperature=temperature,
            max_tokens=max_tokens,
            max_steps=max_steps,
            task_system_prompt=build_system_prompt(knowledge_level, world, codebook_text),
            task_id=task_id,
        )
    finally:
        try:
            world.close()
        except Exception:  # noqa: BLE001 - close is best-effort
            pass
    return result


# --- smoke driver ----------------------------------------------------------- #
TASK_ID = os.environ.get("APPWORLD_TASK_ID", "692c77d_1")
EXPOSED_APIS = [
    "spotify__show_playlist_library",
    "spotify__show_liked_songs",
    "spotify__show_song_reviews",
    "spotify__review_song",
    "spotify__update_song_review",
    "supervisor__complete_task",
]

if __name__ == "__main__":
    res = run_appworld_task(
        task_id=TASK_ID,
        exposed_apis=EXPOSED_APIS,
        provider=os.environ.get("HALLUCI_PROVIDER", "deepseek"),
        model=os.environ.get("HALLUCI_MODEL", "deepseek-chat"),
        knowledge_level=os.environ.get("HALLUCI_KL", "KL1"),
        max_steps=int(os.environ.get("HALLUCI_MAX_STEPS", "25")),
    )
    print("\nDone via the REAL ExperimentRunner._run_single.")
    print("  trajectory_id:", res.trajectory_id, "| steps:", len(res.steps))
    print("  runs_dir     :", DEFAULT_RUNS_DIR)
