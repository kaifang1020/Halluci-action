from __future__ import annotations

from typing import Any

from openai import OpenAI

from research.agents.base_agent import AgentResponse, BaseAgent
from research.config import AgentConfig, default_base_url
from research.tools.registry import get_openai_tools


class OpenAICompatibleAgent(BaseAgent):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        client_kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self.client = OpenAI(**client_kwargs)

    def run_turn(self, messages: list[dict[str, Any]]) -> AgentResponse:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self._prepare_messages(messages),
            tools=get_openai_tools(self.knowledge_level),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        message = response.choices[0].message
        tool_calls = [
            self.make_tool_call(
                tool_name=tool_call.function.name,
                parameters=tool_call.function.arguments,
                call_id=tool_call.id,
            )
            for tool_call in (message.tool_calls or [])
        ]
        return AgentResponse(
            text=message.content or "",
            tool_calls=tool_calls,
            raw_response=response.model_dump(),
        )


class OpenAIAgent(OpenAICompatibleAgent):
    pass


def with_provider_base_url(config: AgentConfig) -> AgentConfig:
    if config.base_url:
        return config
    config.base_url = default_base_url(config.provider)
    return config
