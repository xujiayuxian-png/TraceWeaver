"""Tests for traceweaver.core.tools.loader."""

from __future__ import annotations

import pytest

from traceweaver.core.tools.loader import load_profile_tools
from traceweaver.core.tools.registry import ToolRegistry


_FIX = "tests.core.tools._tool_fixture"


def test_load_single_class() -> None:
    reg = ToolRegistry()
    names = load_profile_tools(
        reg, [{"module": _FIX, "class": "StubTool"}]
    )
    assert names == ["stub"]
    assert reg.has("stub")


def test_load_class_with_init_kwargs() -> None:
    reg = ToolRegistry()
    names = load_profile_tools(
        reg,
        [{"module": _FIX, "class": "StubTool", "init": {"name": "x", "payload": "p"}}],
    )
    assert names == ["x"]


def test_load_via_factory() -> None:
    reg = ToolRegistry()
    names = load_profile_tools(
        reg,
        [{"module": _FIX, "factory": "make_stub", "init": {"name": "fac"}}],
    )
    assert names == ["fac"]


def test_class_and_factory_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        load_profile_tools(
            ToolRegistry(),
            [{"module": _FIX, "class": "StubTool", "factory": "make_stub"}],
        )


def test_missing_class_or_factory() -> None:
    with pytest.raises(ValueError, match="one of 'class' or 'factory'"):
        load_profile_tools(ToolRegistry(), [{"module": _FIX}])


def test_missing_module_attr() -> None:
    with pytest.raises(AttributeError):
        load_profile_tools(
            ToolRegistry(),
            [{"module": _FIX, "class": "NoSuchThing"}],
        )


def test_non_tool_subclass_rejected() -> None:
    with pytest.raises(TypeError, match="not a Tool subclass"):
        load_profile_tools(
            ToolRegistry(),
            [{"module": _FIX, "class": "NotATool"}],
        )


def test_factory_returning_non_tool_rejected() -> None:
    with pytest.raises(TypeError, match="did not return a Tool"):
        load_profile_tools(
            ToolRegistry(),
            [{"module": _FIX, "factory": "broken_factory"}],
        )


def test_unimportable_module() -> None:
    with pytest.raises(ImportError):
        load_profile_tools(
            ToolRegistry(),
            [{"module": "no.such.mod", "class": "X"}],
        )


def test_multiple_tools_preserve_order() -> None:
    reg = ToolRegistry()
    decl = [
        {"module": _FIX, "class": "StubTool", "init": {"name": "a"}},
        {"module": _FIX, "class": "StubTool", "init": {"name": "b"}},
    ]
    names = load_profile_tools(reg, decl)
    assert names == ["a", "b"]
    assert reg.has("a") and reg.has("b")
