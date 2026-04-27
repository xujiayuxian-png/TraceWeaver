"""
Common runtime setup shared by every `traceweaver serve` transport.

`build_serve_context` performs the same end-to-end profile bootstrap as
`traceweaver.cli.analyze` (resolve profile → ingest source with
enrichers → register builtin + profile tools → build knowledge store)
but **does not** instantiate the kernel or the LLM intelligence: the
serve layer only exposes raw tools to an external agent.

Because this helper lives in `traceweaver.serve` and not in
`traceweaver.core`, it is free to depend on `traceweaver.builtin`
without polluting the protocol layer (matches the layering rules in
ROADMAP §2).
"""

from __future__ import annotations

from dataclasses import dataclass

from traceweaver.builtin import register_builtin_sources, register_builtin_tools
from traceweaver.core.profile import Profile
from traceweaver.core.profile.runtime import (
    build_knowledge_store,
    ingest_for_profile,
)
from traceweaver.core.protocols import KnowledgeStore, SourceHandle, ToolContext
from traceweaver.core.source import SourceSpec
from traceweaver.core.source.registry import SourceRegistry
from traceweaver.core.tools.loader import load_profile_tools
from traceweaver.core.tools.registry import ToolRegistry


@dataclass(frozen=True)
class ServeContext:
    """
    Materialised state needed to answer MCP `list_tools` / `call_tool`
    requests. Built once at server startup and reused for every call.

    Capture binding mode: this MVP follows ROADMAP §4 M4' "scheme A"
    — the source is bound at server start and shared by every tool
    invocation. Multi-capture workflows are expected to start one
    server instance per capture (see Claude Desktop `mcp_config.json`
    examples).
    """

    profile: Profile
    handle: SourceHandle
    knowledge: KnowledgeStore | None
    tool_registry: ToolRegistry

    def make_tool_context(self) -> ToolContext:
        """Fresh `ToolContext` for a single tool invocation."""
        return ToolContext(
            source_handle=self.handle,
            knowledge_store=self.knowledge,
            profile_name=self.profile.name,
        )


def build_serve_context(profile: Profile, source_spec: SourceSpec) -> ServeContext:
    """
    Run the full profile bootstrap and return a `ServeContext` ready
    to answer MCP requests.

    Raises propagate to the caller (CLI translates them into exit
    codes); we deliberately do *not* swallow ingest / enricher errors
    here — failing fast is preferable to a server that pretends to be
    healthy but cannot actually answer tool calls.
    """
    source_reg = SourceRegistry()
    register_builtin_sources(source_reg)
    handle = ingest_for_profile(profile, source_spec, registry=source_reg)
    knowledge = build_knowledge_store(profile)

    tool_reg = ToolRegistry()
    register_builtin_tools(tool_reg)
    load_profile_tools(tool_reg, profile.tools)

    return ServeContext(
        profile=profile,
        handle=handle,
        knowledge=knowledge,
        tool_registry=tool_reg,
    )


__all__ = ["ServeContext", "build_serve_context"]
