from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from research.config import AgentConfig

ChatMessage = dict[str, Any]


@dataclass(slots=True)
class ToolCall:
    tool_name: str
    parameters: dict[str, Any]
    call_id: str


@dataclass(slots=True)
class AgentResponse:
    text: str
    tool_calls: list[ToolCall]
    raw_response: dict[str, Any]


class BaseAgent(ABC):
    """
    Base contract for all provider adapters.

    `AnthropicAgent` talks to Anthropic's SDK directly. `OpenAICompatibleAgent`
    subclasses share the OpenAI SDK request/response path and typically only
    override `base_url` and provider metadata.
    """

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.provider = config.provider
        self.model = config.model
        self.api_key = config.api_key
        self.base_url = config.base_url
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens
        self.system_prompt = config.system_prompt
        self.knowledge_level = config.knowledge_level

    @abstractmethod
    def run_turn(self, messages: list[ChatMessage]) -> AgentResponse:
        """
        Send a full conversation turn to the provider and return plain text plus
        structured tool calls.
        """

    def _prepare_messages(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        if self.system_prompt and not any(m.get("role") == "system" for m in messages):
            return [{"role": "system", "content": self.system_prompt}, *messages]
        return messages

    @staticmethod
    def make_tool_call(
        tool_name: str,
        parameters: dict[str, Any] | str | None,
        call_id: str | None = None,
    ) -> ToolCall:
        if isinstance(parameters, str):
            try:
                parsed = json.loads(parameters)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Tool arguments for '{tool_name}' were not valid JSON: {parameters}"
                ) from exc
        else:
            parsed = parameters or {}
        if not isinstance(parsed, dict):
            raise ValueError(f"Tool arguments for '{tool_name}' must decode to an object.")
        return ToolCall(
            tool_name=tool_name,
            parameters=parsed,
            call_id=call_id or f"call_{uuid.uuid4().hex}",
        )

    @staticmethod
    def dump_tool_result(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, default=str)
