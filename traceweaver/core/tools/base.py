"""
Tool contract (platform-v2 §4 Layer 2).

Three kinds of types live here, all frozen pydantic models so they
can be safely cached and passed across threads:

- `ToolSpec`    : what the LLM sees (OpenAI function-calling shape)
- `ToolContext` : the read-only environment a tool runs inside
- `ToolResult`  : the structured value a tool returns

For M1 we deliberately leave SourceHandle / ScopeHandle / CaseMemory
OUT of ToolContext (they're M2/M3 concerns); the field names are reserved
as Optional so future layers can fill them without breaking M1 code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolSpec(BaseModel):
    """
    The public spec the Intelligence layer sees.

    `parameters_schema` is a JSON Schema object (OpenAI-compatible) for
    the tool's input arguments.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    parameters_schema: dict[str, Any] = Field(default_factory=dict)

    def to_openai_tool(self) -> dict[str, Any]:
        """Render this spec in OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema
                or {"type": "object", "properties": {}},
            },
        }


class ToolContext(BaseModel):
    """
    Read-only execution environment passed to every `Tool.run` call.

    - `extras`          : kernel-scoped free-form slot for test hooks etc.
    - `source_handle`   : Layer 0 handle the built-in `query_records` /
                          `get_records_around` tools read from. Typed
                          as `Any` to avoid an import cycle with the
                          source package; at runtime it's a
                          `traceweaver.core.source.SourceHandle`.
    - `scope`           : current analysis scope, reserved for M3+.
    - `profile_name`    : the loaded profile's name (used in log / trace
                          lines; tools are intentionally source-/scope-
                          driven, not profile-branching).
    - `knowledge_store` : the built-in `search_knowledge` tool reads
                          from this when present; typed as `Any` to
                          avoid import cycles.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    extras: dict[str, Any] = Field(default_factory=dict)
    source_handle: Any | None = None
    scope: Any | None = None
    profile_name: str | None = None
    knowledge_store: Any | None = None


class ToolResult(BaseModel):
    """
    Structured tool output.

    Intentionally does not carry any judgment fields (`verdict`,
    `root_cause`, ...). Those are the LLM's job. Core will reject a
    result whose `data` contains forbidden keys (enforced at the
    registry level, not here, so tool authors still write plain dicts).
    """

    model_config = ConfigDict(frozen=True)

    data: dict[str, Any] = Field(default_factory=dict)
    refs: list[str] = Field(default_factory=list)
    truncated: bool = False


class Tool(ABC):
    """
    Base class for all tools. Subclass must set `spec` and implement `run`.

    `run` receives the kernel-built ToolContext plus the LLM-provided
    arguments (already validated by the registry against
    `spec.parameters_schema` before this method is called).
    """

    spec: ToolSpec

    @abstractmethod
    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:  # pragma: no cover
        raise NotImplementedError


__all__ = ["Tool", "ToolContext", "ToolResult", "ToolSpec"]
