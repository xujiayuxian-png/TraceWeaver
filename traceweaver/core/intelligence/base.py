"""
Intelligence protocol: re-exported from core.protocols.

This file exists for backward compatibility; prefer importing directly
from traceweaver.core.protocols.
"""

from __future__ import annotations

from traceweaver.core.protocols import (
    Intelligence,
    IntelligenceRequest,
    IntelligenceResponse,
)

__all__ = [
    "Intelligence",
    "IntelligenceRequest",
    "IntelligenceResponse",
]
