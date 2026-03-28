from __future__ import annotations

from typing import Any

from openai import OpenAI

from research.agents.base_agent import AgentResponse, BaseAgent
from research.agents.openai_agent import OpenAICompatibleAgent, with_provider_base_url
from research.config import AgentConfig, default_base_url
from research.tools.registry import get_openai_tools


class DeepSeekAgent(OpenAICompatibleAgent):
    """
    DeepSeek agent supporting both standard and reasoning models.

    For reasoning models (e.g., deepseek-reasoner), tool calling works differently:
    - The model returns reasoning in a 'reasoning_content' field
    - Tool calls are still supported but may require specific handling

    Usage:
        export DEEPSEEK_API_KEY=your_key_here
        python -m research.harness run --agent deepseek --model deepseek-chat --task "..."
        python -m research.harness run --agent deepseek --model deepseek-reasoner --task "..."
    """

    def __init__(self, config: AgentConfig) -> None:
        super().__init__(with_provider_base_url(config))
        self.is_reasoning_model = "reason" in self.model.lower()

    def run_turn(self, messages: list[dict[str, Any]]) -> AgentResponse:
        """
        Run a conversation turn with DeepSeek.

        For reasoning models, captures both reasoning_content and regular content.
        """
        tools = get_openai_tools(self.knowledge_level)

        # Build request kwargs
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._prepare_messages(messages),
            "max_tokens": self.max_tokens,
        }

        # Reasoning models have specific requirements
        if self.is_reasoning_model:
            # DeepSeek reasoning models don't support temperature
            # and may handle tools differently
            request_kwargs["tools"] = tools
        else:
            request_kwargs["tools"] = tools
            request_kwargs["temperature"] = self.temperature

        response = self.client.chat.completions.create(**request_kwargs)
        message = response.choices[0].message

        # Extract text content
        text_parts = []

        # Check for reasoning content (specific to DeepSeek reasoning models)
        if hasattr(message, "reasoning_content") and message.reasoning_content:
            text_parts.append(f"<reasoning>\n{message.reasoning_content}\n</reasoning>")

        if message.content:
            text_parts.append(message.content)

        # Extract tool calls
        tool_calls = [
            self.make_tool_call(
                tool_name=tool_call.function.name,
                parameters=tool_call.function.arguments,
                call_id=tool_call.id,
            )
            for tool_call in (message.tool_calls or [])
        ]

        return AgentResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            raw_response=response.model_dump(),
        )
