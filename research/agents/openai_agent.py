from __future__ import annotations

import time
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

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

    def _completion_kwargs(self) -> dict[str, Any]:
        return {}

    def run_turn(self, messages: list[dict[str, Any]]) -> AgentResponse:
        response = self._create_completion(messages)
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

    def _create_completion(self, messages: list[dict[str, Any]]) -> Any:
        retryable_errors = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)
        last_error: Exception | None = None
        for attempt in range(6):
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=self._prepare_messages(messages),
                    tools=get_openai_tools(self.knowledge_level),
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    **self._completion_kwargs(),
                )
            except AuthenticationError as exc:
                if not self._is_retryable_auth_error(exc) or attempt == 5:
                    raise
                last_error = exc
                time.sleep(2 ** attempt)
            except retryable_errors as exc:
                last_error = exc
                if attempt == 5:
                    break
                time.sleep(2 ** attempt)
        assert last_error is not None
        raise last_error

    def _is_retryable_auth_error(self, exc: AuthenticationError) -> bool:
        if self.config.provider != "qwen":
            return False
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict) and error.get("code") == "invalid_api_key":
                return True
        return "invalid_api_key" in str(exc)


class OpenAIAgent(OpenAICompatibleAgent):
    pass


def with_provider_base_url(config: AgentConfig) -> AgentConfig:
    if config.base_url:
        return config
    config.base_url = default_base_url(config.provider)
    return config
