from __future__ import annotations

import json
from typing import Any

from anthropic import Anthropic

from research.agents.base_agent import AgentResponse, BaseAgent
from research.config import AgentConfig
from research.tools.registry import get_anthropic_tools


class AnthropicAgent(BaseAgent):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        client_kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self.client = Anthropic(**client_kwargs)

    def run_turn(self, messages: list[dict[str, Any]]) -> AgentResponse:
        response = self.client.messages.create(
            model=self.model,
            system=self.system_prompt,
            messages=self._to_anthropic_messages(messages),
            tools=get_anthropic_tools(self.knowledge_level),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        text_chunks: list[str] = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_chunks.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    self.make_tool_call(
                        tool_name=block.name,
                        parameters=block.input,
                        call_id=block.id,
                    )
                )
        return AgentResponse(
            text="\n".join(chunk for chunk in text_chunks if chunk).strip(),
            tool_calls=tool_calls,
            raw_response=self._dump_response(response),
        )

    def _to_anthropic_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        tool_result_buffer: list[dict[str, Any]] = []

        def flush_tool_results() -> None:
            nonlocal tool_result_buffer
            if tool_result_buffer:
                converted.append({"role": "user", "content": tool_result_buffer})
                tool_result_buffer = []

        for message in messages:
            role = message.get("role")
            if role == "system":
                continue
            if role == "tool":
                tool_result_buffer.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": message["tool_call_id"],
                        "content": message.get("content", ""),
                    }
                )
                continue

            flush_tool_results()
            if role == "assistant" and message.get("tool_calls"):
                content: list[dict[str, Any]] = []
                if message.get("content"):
                    content.append({"type": "text", "text": message["content"]})
                for tool_call in message["tool_calls"]:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tool_call["id"],
                            "name": tool_call["function"]["name"],
                            "input": json.loads(tool_call["function"]["arguments"]),
                        }
                    )
                converted.append({"role": "assistant", "content": content})
                continue

            converted.append({"role": role, "content": message.get("content", "")})

        flush_tool_results()
        return converted

    def _dump_response(self, response: Any) -> dict[str, Any]:
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if hasattr(response, "to_dict"):
            return response.to_dict()
        return json.loads(response.model_dump_json())
