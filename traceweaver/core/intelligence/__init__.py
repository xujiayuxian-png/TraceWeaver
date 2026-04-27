"""Intelligence layer (platform-v2 §4 Layer 4)."""

from traceweaver.core.protocols import (
    Intelligence,
    IntelligenceRequest,
    IntelligenceResponse,
)
from traceweaver.core.intelligence.litellm_adapter import LLMIntelligence

__all__ = [
    "Intelligence",
    "IntelligenceRequest",
    "IntelligenceResponse",
    "LLMIntelligence",
]
