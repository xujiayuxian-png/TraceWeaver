"""
Tests for full JSON Schema validation in kernel (P0-1.3).

Before: kernel only checked `required` keys. Outputs with invalid enum
values ("Success" vs "success") or wrong types passed silently.
After: `_schema_validate_full` catches enum/type/format violations and
triggers the schema_retry path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from traceweaver.core.intelligence.base import (
    Intelligence,
    IntelligenceRequest,
    IntelligenceResponse,
)
from traceweaver.core.kernel import AgentKernel, TaskSpec
from traceweaver.core.kernel.kernel import (
    _schema_missing_keys,
    _schema_validate_full,
)
from traceweaver.core.tools.registry import ToolRegistry


# ---- unit tests on validator ----------------------------------------


def test_validate_full_enum_violation():
    schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["success", "failure", "unclear"]},
        },
        "required": ["verdict"],
    }
    errors = _schema_validate_full(schema, {"verdict": "Success"})
    assert errors, "enum violation should produce errors"


def test_validate_full_type_violation():
    schema = {
        "type": "object",
        "properties": {"confidence": {"type": "number"}},
        "required": ["confidence"],
    }
    errors = _schema_validate_full(schema, {"confidence": "high"})
    assert errors


def test_validate_full_minimum_violation():
    schema = {
        "type": "object",
        "properties": {"confidence": {"type": "number", "minimum": 0, "maximum": 1}},
    }
    errors = _schema_validate_full(schema, {"confidence": 1.5})
    assert errors


def test_validate_full_valid_passes():
    schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["success", "failure"]},
            "confidence": {"type": "number"},
        },
        "required": ["verdict"],
    }
    errors = _schema_validate_full(
        schema, {"verdict": "success", "confidence": 0.9}
    )
    assert errors == []


def test_validate_full_none_schema():
    assert _schema_validate_full(None, {"any": "thing"}) == []


def test_validate_full_none_json():
    errors = _schema_validate_full(
        {"type": "object", "required": ["x"]}, None
    )
    assert errors
    assert "no-json" in errors[0].lower()


def test_missing_keys_still_works_as_fallback():
    schema = {"type": "object", "required": ["a", "b"]}
    assert sorted(_schema_missing_keys(schema, {"a": 1})) == ["b"]
    assert _schema_missing_keys(schema, {"a": 1, "b": 2}) == []


# ---- integration: kernel triggers retry on enum violation ------------


@dataclass
class _ScriptedIntel(Intelligence):
    name: str = "scripted"
    queue: list[IntelligenceResponse] = field(default_factory=list)
    calls: list[IntelligenceRequest] = field(default_factory=list)

    def think(self, request: IntelligenceRequest) -> IntelligenceResponse:  # type: ignore[override]
        self.calls.append(request)
        return self.queue.pop(0)


def _mk_final(as_json: dict) -> IntelligenceResponse:
    return IntelligenceResponse(
        kind="final",
        final_text=json.dumps(as_json),
        final_json=as_json,
    )


def test_kernel_retries_on_enum_violation():
    """
    Regression for P0-1.3: enum violation must trigger schema_retry,
    not pass silently (as it did before the fix).
    """
    schema = {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["success", "failure", "unclear"],
            },
        },
        "required": ["verdict"],
    }
    intel = _ScriptedIntel(
        queue=[
            _mk_final({"verdict": "Success"}),  # wrong case
            _mk_final({"verdict": "success"}),  # valid
        ]
    )
    kernel = AgentKernel(intel, ToolRegistry())

    result = kernel.run(
        TaskSpec(system_prompt="sys", response_schema=schema, max_rounds=5),
        "diagnose",
    )

    assert result.ok
    assert result.final_json == {"verdict": "success"}
    assert result.trace.rounds_used() == 2
    # second call must have received a corrective user turn
    corrective_user = intel.calls[1].messages[-1]
    assert corrective_user.role == "user"
    assert "schema validation" in corrective_user.content.lower()


def test_kernel_retries_on_type_violation():
    """Regression for P0-1.3: type violation triggers retry."""
    schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["verdict", "confidence"],
    }
    intel = _ScriptedIntel(
        queue=[
            _mk_final({"verdict": "ok", "confidence": "high"}),  # wrong type
            _mk_final({"verdict": "ok", "confidence": 0.9}),     # valid
        ]
    )
    kernel = AgentKernel(intel, ToolRegistry())

    result = kernel.run(
        TaskSpec(system_prompt="sys", response_schema=schema, max_rounds=5),
        "diagnose",
    )

    assert result.ok
    assert result.final_json["confidence"] == 0.9
    assert result.trace.rounds_used() == 2
