"""
Cross-layer low-level types.

Only types that need to cross layer boundaries live here.
Layer-internal types stay in their own module (tools/base.py,
intelligence/base.py). Keep this file small.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Role = Literal["system", "user", "assistant", "tool"]


class ToolCall(BaseModel):
    """
    A single tool invocation, as emitted by the intelligence layer and
    consumed by the kernel.

    The shape intentionally mirrors OpenAI function-calling so that the
    default litellm adapter can pass through without translation.

    `arguments` is always the parsed dict the kernel/tool will use.
    `arguments_raw` preserves the provider's exact JSON string when
    known; the adapter uses it when serializing the turn back into a
    prior-assistant message, because some chat templates are sensitive
    to whitespace / key order and silently bias the model otherwise.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    arguments_raw: str | None = None


class Message(BaseModel):
    """
    Chat message flowing through the Agent Kernel.

    `tool_calls` is present only on assistant turns that invoke tools.
    `tool_call_id` is set only on tool-result turns (role='tool').
    """

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


__all__ = ["Role", "ToolCall", "Message"]
