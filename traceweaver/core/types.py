"""
Cross-layer low-level types.

Re-exported from core.protocols for backward compatibility.
Prefer importing directly from traceweaver.core.protocols.
"""

from __future__ import annotations

from traceweaver.core.protocols import Message, ToolCall

Role = str

__all__ = ["Role", "ToolCall", "Message"]
