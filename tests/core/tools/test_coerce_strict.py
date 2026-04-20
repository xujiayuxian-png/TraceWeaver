"""
Tests for strict coercion in ToolRegistry (P1.2).

Before: coerce failure (e.g., "abc" -> integer) returned original string,
causing confusing TypeError inside tools.

After: coerce failure raises ValueError immediately with clear message,
which kernel catches and turns into ToolExecution(ok=False) for LLM to retry.
"""
from __future__ import annotations

import pytest

from traceweaver.core.tools.base import Tool, ToolContext, ToolResult, ToolSpec
from traceweaver.core.tools.registry import ToolRegistry


class DummyTool(Tool):
    """Test tool with various parameter types."""

    spec = ToolSpec(
        name="dummy",
        description="Test tool.",
        parameters_schema={
            "type": "object",
            "properties": {
                "int_field": {"type": "integer"},
                "num_field": {"type": "number"},
                "bool_field": {"type": "boolean"},
                "obj_field": {"type": "object"},
                "arr_field": {"type": "array"},
                "str_field": {"type": "string"},
            },
        },
    )

    def run(self, ctx: ToolContext, **kwargs) -> ToolResult:  # type: ignore[override]
        return ToolResult(data={"received": kwargs})


def _make_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(DummyTool())
    return reg


# ---- coercion success cases ----------------------------------------


def test_coerce_integer_from_string():
    """Valid integer string should coerce."""
    reg = _make_registry()
    result = reg.invoke("dummy", {"int_field": "42"}, ToolContext())
    assert result.data["received"]["int_field"] == 42


def test_coerce_number_from_string():
    """Valid number string should coerce."""
    reg = _make_registry()
    result = reg.invoke("dummy", {"num_field": "3.14"}, ToolContext())
    assert result.data["received"]["num_field"] == 3.14


def test_coerce_boolean_true_variants():
    """Various true strings should coerce to bool."""
    reg = _make_registry()
    for val in ["true", "True", "TRUE", "1", "yes"]:
        result = reg.invoke("dummy", {"bool_field": val}, ToolContext())
        assert result.data["received"]["bool_field"] is True, f"failed for {val}"


def test_coerce_boolean_false_variants():
    """Various false strings should coerce to bool."""
    reg = _make_registry()
    for val in ["false", "False", "FALSE", "0", "no"]:
        result = reg.invoke("dummy", {"bool_field": val}, ToolContext())
        assert result.data["received"]["bool_field"] is False, f"failed for {val}"


def test_coerce_object_from_json_string():
    """JSON object string should coerce to dict."""
    reg = _make_registry()
    result = reg.invoke("dummy", {"obj_field": '{"key": "value"}'}, ToolContext())
    assert result.data["received"]["obj_field"] == {"key": "value"}


def test_coerce_array_from_json_string():
    """JSON array string should coerce to list."""
    reg = _make_registry()
    result = reg.invoke("dummy", {"arr_field": '[1, 2, 3]'}, ToolContext())
    assert result.data["received"]["arr_field"] == [1, 2, 3]


# ---- coercion failure cases (P1.2) --------------------------------


def test_coerce_invalid_integer_raises():
    """Invalid integer string should raise ValueError with clear message."""
    reg = _make_registry()
    with pytest.raises(ValueError, match="cannot coerce.*int_field.*to integer"):
        reg.invoke("dummy", {"int_field": "not_a_number"}, ToolContext())


def test_coerce_invalid_number_raises():
    """Invalid number string should raise ValueError."""
    reg = _make_registry()
    with pytest.raises(ValueError, match="cannot coerce.*num_field.*to number"):
        reg.invoke("dummy", {"num_field": "abc"}, ToolContext())


def test_coerce_invalid_boolean_raises():
    """Invalid boolean string should raise ValueError."""
    reg = _make_registry()
    with pytest.raises(ValueError, match="cannot coerce.*bool_field.*to boolean"):
        reg.invoke("dummy", {"bool_field": "maybe"}, ToolContext())


def test_coerce_invalid_json_object_raises():
    """Invalid JSON for object field should raise ValueError."""
    reg = _make_registry()
    with pytest.raises(ValueError, match="cannot coerce.*obj_field.*object.*invalid JSON"):
        reg.invoke("dummy", {"obj_field": "not json"}, ToolContext())


def test_coerce_object_got_array_raises():
    """JSON array passed to object field should raise ValueError."""
    reg = _make_registry()
    with pytest.raises(ValueError, match="cannot coerce.*obj_field.*object.*got list"):
        reg.invoke("dummy", {"obj_field": "[1, 2, 3]"}, ToolContext())


def test_coerce_array_got_object_raises():
    """JSON object passed to array field should raise ValueError."""
    reg = _make_registry()
    with pytest.raises(ValueError, match="cannot coerce.*arr_field.*array.*got dict"):
        reg.invoke("dummy", {"arr_field": '{"key": "val"}'}, ToolContext())


def test_coerce_invalid_json_array_raises():
    """Invalid JSON for array field should raise ValueError."""
    reg = _make_registry()
    with pytest.raises(ValueError, match="cannot coerce.*arr_field.*array.*invalid JSON"):
        reg.invoke("dummy", {"arr_field": "broken"}, ToolContext())


# ---- non-string values pass through --------------------------------


def test_non_string_values_unchanged():
    """Non-string values should pass through without coercion attempt."""
    reg = _make_registry()
    result = reg.invoke(
        "dummy",
        {"int_field": 42, "obj_field": {"nested": True}, "str_field": "hello"},
        ToolContext(),
    )
    received = result.data["received"]
    assert received["int_field"] == 42
    assert received["obj_field"] == {"nested": True}
    assert received["str_field"] == "hello"


def test_string_field_unchanged():
    """String field should pass through as-is."""
    reg = _make_registry()
    result = reg.invoke("dummy", {"str_field": "any value works"}, ToolContext())
    assert result.data["received"]["str_field"] == "any value works"
