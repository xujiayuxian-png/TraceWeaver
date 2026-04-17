"""
Dynamic tool loading from `profile.yaml:tools`.

A profile declares private tools like this::

    tools:
      - module: traceweaver.profiles.open5gs_5gc.tools.list_ue_sessions
        class: ListUESessionsTool
      - module: traceweaver.profiles.open5gs_5gc.tools.get_ue_timeline
        class: GetUETimelineTool
      # Optional: when the module exposes a pre-built factory callable
      - module: my.module
        factory: make_tool          # callable -> Tool instance

The loader imports each entry, constructs exactly one `Tool` instance,
and registers it with the provided `ToolRegistry`. No singleton, no
global state — every `AgentKernel` gets a fresh registry.

Errors surface the offending entry's index and ref so profile authors
can fix their YAML without grepping the core.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable

from traceweaver.core.tools.base import Tool
from traceweaver.core.tools.registry import ToolRegistry


def load_profile_tools(
    registry: ToolRegistry,
    tools_decl: list[dict[str, Any]],
) -> list[str]:
    """
    Instantiate and register each declared tool.

    Returns the list of registered tool names, in declaration order.
    """
    names: list[str] = []
    for idx, entry in enumerate(tools_decl):
        tool = _instantiate(idx, entry)
        if not isinstance(tool, Tool):
            raise TypeError(
                f"profile.tools[{idx}]: {_ref(entry)!r} did not return a "
                f"Tool instance (got {type(tool).__name__})"
            )
        registry.register(tool)
        names.append(tool.spec.name)
    return names


def _instantiate(idx: int, entry: dict[str, Any]) -> Tool:
    if not isinstance(entry, dict):
        raise ValueError(
            f"profile.tools[{idx}] must be a mapping, got {type(entry).__name__}"
        )
    module_name = entry.get("module")
    if not isinstance(module_name, str) or not module_name:
        raise ValueError(f"profile.tools[{idx}].module is required")

    try:
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        raise ImportError(
            f"profile.tools[{idx}]: cannot import {module_name!r}: {exc}"
        ) from exc

    cls_name = entry.get("class")
    factory_name = entry.get("factory")
    if cls_name and factory_name:
        raise ValueError(
            f"profile.tools[{idx}]: specify exactly one of 'class' or 'factory'"
        )
    if not cls_name and not factory_name:
        raise ValueError(
            f"profile.tools[{idx}]: one of 'class' or 'factory' is required"
        )

    target_name = cls_name or factory_name
    target = getattr(mod, target_name, None)
    if target is None:
        raise AttributeError(
            f"profile.tools[{idx}]: {module_name!r} has no attribute "
            f"{target_name!r}"
        )

    kwargs = entry.get("init") or {}
    if not isinstance(kwargs, dict):
        raise ValueError(
            f"profile.tools[{idx}].init must be a mapping if provided"
        )

    if cls_name:
        if not isinstance(target, type) or not issubclass(target, Tool):
            raise TypeError(
                f"profile.tools[{idx}]: {module_name}:{cls_name} is not a Tool subclass"
            )
        return target(**kwargs)

    factory: Callable[..., Tool] = target
    if not callable(factory):
        raise TypeError(
            f"profile.tools[{idx}]: factory {module_name}:{factory_name} is not callable"
        )
    return factory(**kwargs)


def _ref(entry: dict[str, Any]) -> str:
    mod = entry.get("module", "?")
    target = entry.get("class") or entry.get("factory") or "?"
    return f"{mod}:{target}"


__all__ = ["load_profile_tools"]
