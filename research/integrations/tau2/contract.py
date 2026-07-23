"""Versioned data contract between Tau2 and the Halluci-Action evaluators."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceMetadata(ContractModel):
    benchmark: Literal["tau2"] = "tau2"
    run_id: str
    task_id: str
    trial: int | None = None
    seed: int | None = None
    domain: str | None = None
    termination_reason: str | None = None
    git_commit: str | None = None


class CanonicalToolCall(ContractModel):
    call_id: str
    tool_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    requestor: Literal["assistant"] = "assistant"
    source_turn_idx: int


class SourceToolCall(ContractModel):
    call_id: str
    tool_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    requestor: Literal["assistant", "user"]


class CanonicalToolResult(ContractModel):
    action_id: str
    call_id: str
    tool_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    status: Literal["success", "error", "unknown"] = "unknown"
    error: bool | None = None
    source_turn_idx: int | None = None
    audit_record_index: int | None = None


class CanonicalStep(ContractModel):
    """Agent-only projection consumed by the current claim/action pipeline."""

    step_id: int
    source_turn_idx: int
    assistant_text: str = ""
    tool_calls: list[CanonicalToolCall] = Field(default_factory=list)
    tool_results: list[CanonicalToolResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def results_reference_calls(self) -> "CanonicalStep":
        call_ids = {call.call_id for call in self.tool_calls}
        orphan_ids = {
            result.call_id for result in self.tool_results if result.call_id not in call_ids
        }
        if orphan_ids:
            raise ValueError(
                "tool_results must reference tool_calls in the same step: "
                f"{sorted(orphan_ids)}"
            )
        return self


class SourceEvent(ContractModel):
    """Chronological source event retained for multi-turn context and replay."""

    turn_idx: int
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[SourceToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    requestor: Literal["assistant", "user"] | None = None
    error: bool | None = None
    timestamp: str | None = None


class AgentContext(ContractModel):
    """Context that was available to the evaluated Tau2 agent."""

    policy: str | None = None
    tool_definitions: list[dict[str, Any]] = Field(default_factory=list)


class ReferenceSolution(ContractModel):
    actions: list[dict[str, Any]] = Field(default_factory=list)
    binding: Literal["required", "reference_only"] = "reference_only"


class EvaluatorContext(ContractModel):
    """Hidden task metadata. This block must never be included in agent prompts."""

    visibility: Literal["evaluator_only"] = "evaluator_only"
    task_description: dict[str, Any] | None = None
    hidden_user_scenario: dict[str, Any] | None = None
    initial_state: dict[str, Any] | None = None
    reference_solution: ReferenceSolution = Field(default_factory=ReferenceSolution)
    env_assertions: list[dict[str, Any]] = Field(default_factory=list)
    communicate_info: list[str] = Field(default_factory=list)
    nl_assertions: list[str] = Field(default_factory=list)
    reward_basis: list[str] = Field(default_factory=list)
    native_reward_info: dict[str, Any] | None = None


class InteractionMetrics(ContractModel):
    assistant_turns: int
    user_turns: int
    assistant_tool_calls: int
    user_tool_calls: int
    is_multi_turn: bool


class CanonicalTrajectory(ContractModel):
    """Portable trajectory plus an agent-only legacy projection.

    `steps` deliberately keeps the existing Halluci-Action keys so the current
    claim extraction and grounding code can read adapted files without importing
    Tau2. `events` preserves multi-turn context and user-side actions that must
    not enter the agent action denominator.
    """

    schema_version: Literal["halluci_action_canonical_trajectory_v1"] = (
        "halluci_action_canonical_trajectory_v1"
    )
    trajectory_id: str
    task_id: str
    task: str
    agent: str
    model: str
    knowledge_level: Literal["external_policy"] = "external_policy"
    visibility_condition: Literal["external_adapter"] = "external_adapter"
    visible_context: dict[str, Any] = Field(default_factory=dict)
    audit_file: str | None = None
    source: SourceMetadata
    agent_context: AgentContext = Field(default_factory=AgentContext)
    evaluator_context: EvaluatorContext = Field(default_factory=EvaluatorContext)
    interaction_metrics: InteractionMetrics
    events: list[SourceEvent] = Field(default_factory=list)
    steps: list[CanonicalStep] = Field(default_factory=list)
    adapter_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def step_ids_are_unique_and_ordered(self) -> "CanonicalTrajectory":
        step_ids = [step.step_id for step in self.steps]
        if step_ids != list(range(1, len(step_ids) + 1)):
            raise ValueError("step_id must be contiguous and one-indexed")
        source_turns = [step.source_turn_idx for step in self.steps]
        if source_turns != sorted(source_turns):
            raise ValueError("steps must be ordered by source_turn_idx")
        return self
