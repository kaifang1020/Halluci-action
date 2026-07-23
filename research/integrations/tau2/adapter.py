"""Adapt Tau2 result JSON into the Halluci-Action canonical trajectory contract."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .contract import (
    AgentContext,
    CanonicalStep,
    CanonicalToolCall,
    CanonicalToolResult,
    CanonicalTrajectory,
    EvaluatorContext,
    InteractionMetrics,
    ReferenceSolution,
    SourceEvent,
    SourceMetadata,
    SourceToolCall,
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _parse_tool_content(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def _turn_idx(message: dict[str, Any], fallback: int) -> int:
    value = message.get("turn_idx")
    return value if isinstance(value, int) else fallback


def _find_task(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    for task in tasks:
        if str(task.get("id")) == task_id:
            return task
    return {}


def _first_user_request(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            content = message["content"].strip()
            if content:
                return content
    return ""


def _source_tool_calls(message: dict[str, Any]) -> list[SourceToolCall]:
    calls = []
    default_requestor = "user" if message.get("role") == "user" else "assistant"
    source_turn_idx = message.get("turn_idx", "unknown")
    for index, raw_call in enumerate(_as_list(message.get("tool_calls"))):
        call = _as_dict(raw_call)
        requestor = call.get("requestor", default_requestor)
        if requestor not in {"assistant", "user"}:
            requestor = default_requestor
        calls.append(
            SourceToolCall(
                call_id=str(
                    call.get("id") or f"source_t{source_turn_idx}_call{index}"
                ),
                tool_name=str(call.get("name") or ""),
                parameters=deepcopy(_as_dict(call.get("arguments"))),
                requestor=requestor,
            )
        )
    return calls


def _build_events(messages: list[dict[str, Any]]) -> list[SourceEvent]:
    events = []
    for index, message in enumerate(messages):
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            continue
        events.append(
            SourceEvent(
                turn_idx=_turn_idx(message, index),
                role=role,
                content=message.get("content"),
                tool_calls=_source_tool_calls(message),
                tool_call_id=(
                    str(message.get("id"))
                    if role == "tool" and message.get("id") is not None
                    else None
                ),
                requestor=message.get("requestor") if role == "tool" else None,
                error=message.get("error") if role == "tool" else None,
                timestamp=message.get("timestamp"),
            )
        )
    return sorted(events, key=lambda event: event.turn_idx)


def _tool_results_by_id(
    messages: list[dict[str, Any]], warnings: list[str]
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for index, message in enumerate(messages):
        if message.get("role") != "tool" or message.get("id") is None:
            continue
        call_id = str(message["id"])
        if call_id in results:
            warnings.append(f"duplicate ToolMessage id: {call_id}")
        results[call_id] = {**message, "_source_index": index}
    return results


def _build_steps(
    messages: list[dict[str, Any]], warnings: list[str]
) -> list[CanonicalStep]:
    result_index = _tool_results_by_id(messages, warnings)
    steps = []
    consumed_result_ids: set[str] = set()

    for message_index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        source_turn_idx = _turn_idx(message, message_index)
        tool_calls = []
        tool_results = []

        for call_index, raw_call in enumerate(_as_list(message.get("tool_calls"))):
            call = _as_dict(raw_call)
            if call.get("requestor", "assistant") != "assistant":
                continue
            call_id = str(
                call.get("id") or f"tau2_t{source_turn_idx}_call{call_index}"
            )
            tool_name = str(call.get("name") or "")
            parameters = deepcopy(_as_dict(call.get("arguments")))
            tool_calls.append(
                CanonicalToolCall(
                    call_id=call_id,
                    tool_name=tool_name,
                    parameters=parameters,
                    source_turn_idx=source_turn_idx,
                )
            )

            raw_result = result_index.get(call_id)
            if raw_result is None:
                warnings.append(f"missing ToolMessage for assistant call: {call_id}")
                continue
            consumed_result_ids.add(call_id)
            error = raw_result.get("error")
            status = "error" if error is True else "success" if error is False else "unknown"
            tool_results.append(
                CanonicalToolResult(
                    action_id=f"tau2_t{source_turn_idx}_action{call_index}",
                    call_id=call_id,
                    tool_name=tool_name,
                    parameters=parameters,
                    result=_parse_tool_content(raw_result.get("content")),
                    status=status,
                    error=error if isinstance(error, bool) else None,
                    source_turn_idx=_turn_idx(
                        raw_result, int(raw_result.get("_source_index", message_index))
                    ),
                )
            )

        steps.append(
            CanonicalStep(
                step_id=len(steps) + 1,
                source_turn_idx=source_turn_idx,
                assistant_text=str(message.get("content") or ""),
                tool_calls=tool_calls,
                tool_results=tool_results,
            )
        )

    assistant_call_ids = {
        call.call_id for step in steps for call in step.tool_calls
    }
    for call_id, result in result_index.items():
        if result.get("requestor") == "assistant" and call_id not in consumed_result_ids:
            warnings.append(f"orphan assistant ToolMessage: {call_id}")
        if call_id in assistant_call_ids and result.get("requestor") == "user":
            warnings.append(f"requestor mismatch for ToolMessage: {call_id}")
    return steps


def adapt_tau2_run(
    result_payload: dict[str, Any],
    simulation: dict[str, Any],
    task: dict[str, Any] | None = None,
    *,
    policy: str | None = None,
    tool_definitions: list[dict[str, Any]] | None = None,
) -> CanonicalTrajectory:
    """Build one canonical trajectory from a Tau2 result and SimulationRun.

    The function accepts plain dictionaries so Halluci-Action does not need Tau2
    installed. Callers selecting from a multi-run result file should use
    `select_tau2_run` below.
    """

    warnings: list[str] = []
    messages = [
        _as_dict(message) for message in _as_list(simulation.get("messages"))
    ]
    if not messages:
        warnings.append("simulation has no half-duplex messages")

    task_id = str(simulation.get("task_id") or "")
    task = task or _find_task(
        [_as_dict(item) for item in _as_list(result_payload.get("tasks"))], task_id
    )
    if not task:
        warnings.append(f"task definition not found: {task_id}")

    info = _as_dict(result_payload.get("info"))
    environment_info = _as_dict(info.get("environment_info"))
    agent_info = _as_dict(info.get("agent_info"))
    evaluation = _as_dict(task.get("evaluation_criteria"))
    reward_basis = [str(value) for value in _as_list(evaluation.get("reward_basis"))]
    binding = "required" if "ACTION" in reward_basis else "reference_only"

    steps = _build_steps(messages, warnings)
    events = _build_events(messages)
    user_turns = sum(event.role == "user" for event in events)
    assistant_turns = sum(event.role == "assistant" for event in events)
    assistant_tool_calls = sum(len(step.tool_calls) for step in steps)
    user_tool_calls = sum(
        1
        for event in events
        for call in event.tool_calls
        if call.requestor == "user"
    )
    visible_task = _first_user_request(messages)
    if not visible_task:
        warnings.append("no visible user request found")

    run_id = str(simulation.get("id") or f"tau2-{task_id}")
    return CanonicalTrajectory(
        trajectory_id=run_id,
        task_id=task_id,
        task=visible_task,
        agent=str(agent_info.get("implementation") or "tau2_agent"),
        model=str(agent_info.get("llm") or "unknown"),
        visible_context={
            "dialogue_mode": simulation.get("mode") or "half_duplex",
            "domain": environment_info.get("domain_name"),
        },
        source=SourceMetadata(
            run_id=run_id,
            task_id=task_id,
            trial=simulation.get("trial"),
            seed=simulation.get("seed"),
            domain=environment_info.get("domain_name"),
            termination_reason=simulation.get("termination_reason"),
            git_commit=info.get("git_commit"),
        ),
        agent_context=AgentContext(
            policy=policy if policy is not None else environment_info.get("policy"),
            tool_definitions=(
                deepcopy(tool_definitions)
                if tool_definitions is not None
                else [
                    _as_dict(tool)
                    for tool in _as_list(environment_info.get("tool_defs"))
                ]
            ),
        ),
        evaluator_context=EvaluatorContext(
            task_description=_as_dict(task.get("description")) or None,
            hidden_user_scenario=_as_dict(task.get("user_scenario")) or None,
            initial_state=_as_dict(task.get("initial_state")) or None,
            reference_solution=ReferenceSolution(
                actions=[
                    deepcopy(_as_dict(action))
                    for action in _as_list(evaluation.get("actions"))
                ],
                binding=binding,
            ),
            env_assertions=[
                deepcopy(_as_dict(assertion))
                for assertion in _as_list(evaluation.get("env_assertions"))
            ],
            communicate_info=[
                str(value) for value in _as_list(evaluation.get("communicate_info"))
            ],
            nl_assertions=[
                str(value) for value in _as_list(evaluation.get("nl_assertions"))
            ],
            reward_basis=reward_basis,
            native_reward_info=_as_dict(simulation.get("reward_info")) or None,
        ),
        interaction_metrics=InteractionMetrics(
            assistant_turns=assistant_turns,
            user_turns=user_turns,
            assistant_tool_calls=assistant_tool_calls,
            user_tool_calls=user_tool_calls,
            is_multi_turn=user_turns > 1,
        ),
        events=events,
        steps=steps,
        adapter_warnings=warnings,
    )

def select_tau2_run(
    result_payload: dict[str, Any],
    *,
    task_id: str | None = None,
    trial: int | None = None,
    simulation_index: int = 0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Select a SimulationRun and its Task from a Tau2 result file."""

    simulations = [
        _as_dict(item) for item in _as_list(result_payload.get("simulations"))
    ]
    if task_id is not None:
        simulations = [
            run for run in simulations if str(run.get("task_id")) == str(task_id)
        ]
    if trial is not None:
        simulations = [run for run in simulations if run.get("trial") == trial]
    if not simulations:
        raise ValueError("no Tau2 simulation matched the selection")
    if simulation_index < 0 or simulation_index >= len(simulations):
        raise IndexError(
            f"simulation_index {simulation_index} outside 0..{len(simulations) - 1}"
        )
    simulation = simulations[simulation_index]
    selected_task_id = str(simulation.get("task_id") or "")
    task = _find_task(
        [_as_dict(item) for item in _as_list(result_payload.get("tasks"))],
        selected_task_id,
    )
    return simulation, task
