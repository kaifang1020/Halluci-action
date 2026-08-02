from __future__ import annotations

from research.agents.openai_agent import OpenAICompatibleAgent, with_provider_base_url
from research.config import AgentConfig


class QwenAgent(OpenAICompatibleAgent):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(with_provider_base_url(config))

    def _completion_kwargs(self) -> dict[str, object]:
        return {"extra_body": {"enable_thinking": False}}
