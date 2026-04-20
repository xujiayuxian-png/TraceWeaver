"""
Intelligence protocol: the boundary between "deciding what to do" and
"actually doing it".

Anything that can look at a conversation-plus-tools and emit either a
batch of tool calls or a final answer can be an `Intelligence`:

- `LLMIntelligence`     : a chat model via litellm  (M1)
- `MCPAgentIntelligence`: delegate to an external agent over MCP (M5)
- test doubles          : a fake that returns a scripted sequence

The kernel only ever talks to this contract; it never imports litellm,
never sees a provider name, never parses a chat template.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from traceweaver.core.types import Message, ToolCall


class IntelligenceRequest(BaseModel):
    """What the kernel hands to `Intelligence.think`."""

    model_config = ConfigDict(frozen=True)

    system_prompt: str
    messages: list[Message] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    response_schema: dict[str, Any] | None = None


class IntelligenceResponse(BaseModel):
    """
    What the kernel gets back.

    `kind="tool_calls"`  : run the listed calls, loop again
    `kind="final"`       : we're done, `final_text` / `final_json` carries the answer

    `assistant_content` carries the provider's raw assistant-turn content
    verbatim (often empty or just whitespace for tool-call turns). The
    kernel threads this back into the next request so the model sees
    its own prior turn exactly as it produced it.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["tool_calls", "final"]
    tool_calls: list[ToolCall] = Field(default_factory=list)
    final_text: str | None = None
    final_json: dict[str, Any] | None = None
    reasoning: str | None = None
    assistant_content: str = ""
    provider_raw: dict[str, Any] | None = None
    # Telemetry (P1.1)
    tokens_used: int | None = None  # Total tokens for this round (prompt + completion)
    cost_usd: float | None = None   # Estimated cost for this round


class Intelligence(ABC):
    """Any decision-maker the Agent Kernel can drive."""

    name: str

    @abstractmethod
    def think(self, request: IntelligenceRequest) -> IntelligenceResponse:  # pragma: no cover
        raise NotImplementedError


__all__ = [
    "Intelligence",
    "IntelligenceRequest",
    "IntelligenceResponse",
]
