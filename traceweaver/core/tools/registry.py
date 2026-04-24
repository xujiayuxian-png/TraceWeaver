"""Tool registry: registration, OpenAI-spec export, dispatch."""
from __future__ import annotations
from typing import Any
from traceweaver.core.protocols import Tool, ToolContext, ToolResult


_FORBIDDEN_DATA_KEYS = frozenset(
    {"verdict", "root_cause", "failure_point", "confidence"}
)


class ToolRegistry:
    """Name-indexed container of tools the kernel can dispatch to."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = tool

    def register_all(self, tools: list[Tool]) -> None:
        for t in tools:
            self.register(t)

    def has(self, name: str) -> bool:
        return name in self._tools

    def __iter__(self):
        return iter(self._tools.values())

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def specs(self) -> list[dict[str, Any]]:
        """Render every registered tool as an OpenAI function-calling entry."""
        return [t.spec.to_openai_tool() for t in self._tools.values()]

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        ctx: ToolContext,
    ) -> ToolResult:
        """Validate args, call the tool, enforce result contract."""
        tool = self.get(name)
        coerced = self._validate_arguments(tool, arguments)
        result = tool.run(ctx, **coerced)
        self._enforce_result_contract(name, result)
        return result

    @staticmethod
    def _validate_arguments(tool: Tool, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Minimal M1 arg validation:
          - required keys must be present
          - ints/floats/bools get a best-effort coercion from strings
            (LLM output is frequently stringified numerics)

        Full JSON Schema validation is deferred; the contract here is
        stable enough to swap implementations later.
        """
        if not isinstance(arguments, dict):
            raise TypeError(
                f"tool {tool.spec.name} arguments must be a dict, got {type(arguments).__name__}"
            )

        schema = tool.spec.parameters_schema or {}
        props = schema.get("properties", {}) or {}
        required = schema.get("required", []) or []

        missing = [k for k in required if k not in arguments]
        if missing:
            raise ValueError(
                f"tool {tool.spec.name} missing required args: {missing}"
            )

        coerced: dict[str, Any] = {}
        for key, raw in arguments.items():
            expected = props.get(key, {}).get("type") if isinstance(props.get(key), dict) else None
            try:
                coerced[key] = ToolRegistry._coerce(raw, expected, key)
            except ValueError as e:
                raise ValueError(f"tool {tool.spec.name} argument coercion failed: {e}") from e
        return coerced

    @staticmethod
    def _coerce(value: Any, expected: str | None, key: str = "") -> Any:
        """
        Coerce string values to expected types.
        Raises ValueError on coercion failure (P1.2: fail fast for better diagnostics).
        """
        if expected is None or not isinstance(value, str):
            return value
        if expected == "integer":
            try:
                return int(value)
            except (TypeError, ValueError) as e:
                raise ValueError(f"cannot coerce {key!r}={value!r} to integer") from e
        if expected == "number":
            try:
                return float(value)
            except (TypeError, ValueError) as e:
                raise ValueError(f"cannot coerce {key!r}={value!r} to number") from e
        if expected == "boolean":
            low = value.strip().lower()
            if low in {"true", "1", "yes"}:
                return True
            if low in {"false", "0", "no"}:
                return False
            raise ValueError(f"cannot coerce {key!r}={value!r} to boolean")
        if expected in {"object", "array"}:
            # Some models serialize nested structures as JSON strings
            # (Qwen does this intermittently). Must parse to expected shape.
            import json as _json

            try:
                parsed = _json.loads(value)
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"cannot coerce {key!r} to {expected}: invalid JSON"
                ) from e
            if expected == "object" and isinstance(parsed, dict):
                return parsed
            if expected == "array" and isinstance(parsed, list):
                return parsed
            raise ValueError(
                f"cannot coerce {key!r} to {expected}: got {type(parsed).__name__} instead"
            )
        return value

    @staticmethod
    def _enforce_result_contract(name: str, result: ToolResult) -> None:
        forbidden = _FORBIDDEN_DATA_KEYS & set(result.data.keys())
        if forbidden:
            raise ValueError(
                f"tool {name} returned forbidden data keys "
                f"(judgement belongs to the LLM, not tools): {sorted(forbidden)}"
            )


__all__ = ["ToolRegistry"]
