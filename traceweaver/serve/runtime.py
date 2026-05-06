"""
Common runtime setup shared by every `traceweaver serve` transport.

`build_serve_context` performs the same end-to-end profile bootstrap as
`traceweaver.cli.analyze` (resolve profile → ingest source with
enrichers → register builtin + profile tools → build knowledge store)
but **does not** instantiate the kernel or the LLM intelligence: the
serve layer only exposes raw tools to an external agent.

Capture binding is deferred to runtime: the MCP server starts without a
capture loaded.  The agent calls ``load_capture(path=...)`` to ingest a
pcap on demand, and can call it again to swap to a different file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from traceweaver.builtin import register_builtin_sources, register_builtin_tools
from traceweaver.core.profile import Profile
from traceweaver.core.profile.runtime import (
    build_knowledge_store,
    ingest_for_profile,
)
from traceweaver.core.protocols import KnowledgeStore, SourceHandle, ToolContext, ToolSpec
from traceweaver.core.source import SourceSpec
from traceweaver.core.source.registry import SourceRegistry
from traceweaver.core.tools.loader import load_profile_tools
from traceweaver.core.tools.registry import ToolRegistry
from traceweaver.serve.session import CaptureSession


@dataclass(frozen=True)
class ServeContext:
    """
    Materialised state for one profile in the MCP server.

    Holds the profile's tool registry, knowledge store, and a mutable
    ``CaptureSession`` that tools use to access the current capture.
    The capture is **not** bound at startup — it is loaded at runtime
    via the ``load_capture`` meta-tool.
    """

    profile: Profile
    session: CaptureSession
    knowledge: KnowledgeStore | None
    tool_registry: ToolRegistry

    def make_tool_context(self) -> ToolContext:
        """Fresh `ToolContext` for a single tool invocation."""
        return ToolContext(
            source_handle=self.session,
            knowledge_store=self.knowledge,
            profile_name=self.profile.name,
        )


def build_serve_context(
    profile: Profile,
    source_spec: SourceSpec | None = None,
) -> ServeContext:
    """
    Build a `ServeContext` for *profile*.

    If *source_spec* is provided the capture is loaded immediately
    (legacy behaviour); otherwise the session starts empty and the
    agent loads a capture later via ``load_capture``.
    """
    source_reg = SourceRegistry()
    register_builtin_sources(source_reg)

    session = CaptureSession()
    if source_spec is not None:
        handle = ingest_for_profile(profile, source_spec, registry=source_reg)
        session.load(handle, source_spec.uri)

    knowledge = build_knowledge_store(profile)

    tool_reg = ToolRegistry()
    register_builtin_tools(tool_reg)
    load_profile_tools(tool_reg, profile.tools)

    # Meta-tools: load_capture + list_captures
    tool_reg.register(LoadCaptureTool(session, profile))
    tool_reg.register(ListCapturesTool({profile.name: session}))

    return ServeContext(
        profile=profile,
        session=session,
        knowledge=knowledge,
        tool_registry=tool_reg,
    )


# ---- load_capture tool ------------------------------------------------


class LoadCaptureTool:
    """Meta-tool: ingest a pcap/pcapng at runtime and bind it to the session."""

    def __init__(self, session: CaptureSession, profile: Profile) -> None:
        self._session = session
        self._profile = profile
        self.spec = ToolSpec(
            name="load_capture",
            description=(
                "Load a pcap or pcapng file for analysis.  Call this "
                "before using any diagnostic tools.  You can call it "
                "again with a different path to switch captures."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the pcap/pcapng file.",
                    },
                },
                "required": ["path"],
            },
        )

    def run(self, ctx, **kwargs):
        from traceweaver.core.protocols import ToolResult

        path_str = kwargs.get("path")
        if not path_str or not isinstance(path_str, str):
            return ToolResult(data={"error": "path is required"})

        path = Path(path_str)
        if not path.is_file():
            return ToolResult(data={"error": f"file not found: {path_str}"})

        source_reg = SourceRegistry()
        register_builtin_sources(source_reg)

        source_cfg = self._profile.source_config.get("pcap", {})
        source_spec = SourceSpec(
            kind="pcap",
            uri=str(path),
            options=dict(source_cfg),
        )

        try:
            handle = ingest_for_profile(
                self._profile, source_spec, registry=source_reg
            )
        except Exception as exc:
            return ToolResult(data={"error": f"{type(exc).__name__}: {exc}"})

        self._session.load(handle, str(path))
        meta = handle.metadata()
        return ToolResult(data={
            "status": "ok",
            "path": str(path),
            "metadata": meta,
        })


# ---- list_profiles + list_captures tools ------------------------------


class ListProfilesTool:
    """Meta-tool: list loaded profiles and their status."""

    def __init__(self, profile_names: list[str], default: str) -> None:
        self._names = profile_names
        self._default = default
        self.spec = ToolSpec(
            name="list_profiles",
            description=(
                "List all loaded profiles and which is the default. "
                "Use this to discover available profiles before calling "
                "profile-specific tools."
            ),
            parameters_schema={"type": "object", "properties": {}, "required": []},
        )

    def run(self, ctx, **kwargs):
        from traceweaver.core.protocols import ToolResult
        profiles = []
        for name in self._names:
            profiles.append({
                "name": name,
                "is_default": name == self._default,
            })
        return ToolResult(data={"profiles": profiles, "default": self._default})


class ListCapturesTool:
    """Meta-tool: show which capture is loaded per profile."""

    def __init__(self, sessions: dict[str, CaptureSession]) -> None:
        self._sessions = sessions
        self.spec = ToolSpec(
            name="list_captures",
            description=(
                "Show the currently loaded capture for each profile. "
                "Returns null for profiles that have no capture loaded yet."
            ),
            parameters_schema={"type": "object", "properties": {}, "required": []},
        )

    def run(self, ctx, **kwargs):
        from traceweaver.core.protocols import ToolResult
        captures = {}
        for name, session in self._sessions.items():
            captures[name] = session.capture_path
        return ToolResult(data={"captures": captures})


# ---- MultiServeContext ------------------------------------------------


class MultiServeContext:
    """
    Materialised state for serving multiple profiles simultaneously.
    Each profile gets its own ``ServeContext`` with its own
    ``CaptureSession``.  Profile-specific tools are prefixed with
    ``<profile>__``; built-in tools route to the default profile.
    """

    def __init__(
        self,
        contexts: dict[str, ServeContext],
        default_profile: str,
    ) -> None:
        self.contexts = contexts
        self.default_profile = default_profile
        self._merged_registry = self._build_merged_registry()

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._merged_registry

    def make_tool_context(self, profile_name: str | None = None) -> ToolContext:
        name = profile_name or self.default_profile
        ctx = self.contexts[name]
        return ctx.make_tool_context()

    def profile_for_tool(self, tool_name: str) -> tuple[str, ServeContext]:
        if "__" in tool_name:
            prefix, _ = tool_name.split("__", 1)
            if prefix in self.contexts:
                return prefix, self.contexts[prefix]
        return self.default_profile, self.contexts[self.default_profile]

    def _build_merged_registry(self) -> ToolRegistry:
        merged = ToolRegistry()

        # 1. Built-in tools (unprefixed).
        from traceweaver.builtin import register_builtin_tools
        register_builtin_tools(merged)

        # 2. Profile-specific tools (prefixed).
        for name, ctx in self.contexts.items():
            for tool in ctx.tool_registry.values():
                if _is_builtin(tool.spec.name):
                    continue
                prefixed = _PrefixTool.wrap(tool, name)
                merged.register(prefixed)

        # 3. Meta-tools.
        merged.register(ListProfilesTool(
            list(self.contexts.keys()), self.default_profile
        ))
        merged.register(ListCapturesTool(
            {n: ctx.session for n, ctx in self.contexts.items()}
        ))

        # 4. load_capture — prefixed per profile, plus one unprefixed
        #    that targets the default profile.
        default_ctx = self.contexts[self.default_profile]
        merged.register(LoadCaptureTool(default_ctx.session, default_ctx.profile))
        for name, ctx in self.contexts.items():
            prefixed = _PrefixTool.wrap(
                LoadCaptureTool(ctx.session, ctx.profile), name
            )
            merged.register(prefixed)

        return merged


def _is_builtin(tool_name: str) -> bool:
    return tool_name in {"query_records", "get_records_around", "search_knowledge"}


class _PrefixTool:
    @staticmethod
    def wrap(tool, profile_name: str):
        from traceweaver.core.protocols import Tool, ToolContext, ToolResult

        prefix = f"{profile_name}__"
        original_name = tool.spec.name

        prefixed_spec = ToolSpec(
            name=f"{prefix}{original_name}",
            description=f"[{profile_name}] {tool.spec.description}",
            parameters_schema=tool.spec.parameters_schema,
        )

        class _Wrapped(Tool):
            spec = prefixed_spec
            _inner = tool
            _profile = profile_name

            def run(self, ctx: ToolContext, **kwargs) -> ToolResult:
                return self._inner.run(ctx, **kwargs)

        return _Wrapped()


def build_multi_serve_context(
    pairs: list[tuple[Profile, SourceSpec | None]],
    default_profile: str | None = None,
) -> MultiServeContext:
    """
    Build a `MultiServeContext` from (profile, optional source_spec) pairs.

    source_spec may be None — the capture is loaded later via
    ``load_capture``.
    """
    if not pairs:
        raise ValueError("at least one profile is required")

    available = [p.name for p, _ in pairs]
    default = default_profile or available[0]
    if default not in available:
        raise ValueError(
            f"default_profile {default!r} not found; "
            f"available: {available}"
        )

    contexts: dict[str, ServeContext] = {}
    for profile, source_spec in pairs:
        contexts[profile.name] = build_serve_context(profile, source_spec)

    return MultiServeContext(contexts=contexts, default_profile=default)


__all__ = [
    "ServeContext",
    "build_serve_context",
    "MultiServeContext",
    "build_multi_serve_context",
    "LoadCaptureTool",
    "ListCapturesTool",
]
