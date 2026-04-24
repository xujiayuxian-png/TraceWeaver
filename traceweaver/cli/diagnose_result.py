"""
Human-readable rendering of an `AgentResult`.

Kept tiny and dependency-free so both the CLI and smoke scripts can use
it. Rendering is line-oriented and UTF-8 safe.
"""

from __future__ import annotations

import json
from typing import Any

from traceweaver.core.trace import AgentResult


def format_result(result: AgentResult, *, show_trace: bool = False) -> str:
    lines: list[str] = []
    lines.append(f"stop_reason: {result.stop_reason}")
    lines.append(f"rounds_used: {len(result.trace.events)}")
    tool_calls_total = sum(
        len(e.tool_executions) for e in result.trace.events if not e.is_final
    )
    lines.append(f"tool_calls_total: {tool_calls_total}")

    if result.final_json is not None:
        lines.append("")
        lines.append("final_json:")
        lines.append(_indent(json.dumps(result.final_json, indent=2, ensure_ascii=False)))
    elif result.final_text:
        lines.append("")
        lines.append("final_text:")
        lines.append(_indent(result.final_text))

    if result.error:
        lines.append("")
        lines.append(f"error: {result.error}")

    if show_trace:
        lines.append("")
        lines.append("trace:")
        lines.extend(_format_trace(result))

    return "\n".join(lines)


def _indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + ln for ln in text.splitlines()) or prefix


def _format_trace(result: AgentResult) -> list[str]:
    out: list[str] = []
    for ev in result.trace.events:
        out.append(f"  round {ev.round_index}: final={ev.is_final}")
        if ev.assistant_content:
            snippet = ev.assistant_content.strip().replace("\n", " ")
            if len(snippet) > 160:
                snippet = snippet[:157] + "..."
            out.append(f"    assistant: {snippet}")
        for ex in ev.tool_executions:
            status = "ok" if ex.ok else f"ERR {ex.error}"
            args = _short(json.dumps(ex.call.arguments, ensure_ascii=False))
            out.append(f"    tool {ex.call.name}({args}) -> {status}")
            if ex.ok:
                body = _short(json.dumps(ex.data, ensure_ascii=False))
                out.append(f"      data: {body}")
    return out


def _short(text: str, limit: int = 180) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


__all__ = ["format_result"]
