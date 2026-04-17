"""
Layer 0 — Source abstractions (see docs/design/platform-v2.md §4 Layer 0).

A Source turns a URI (+ kind-specific options) into a SourceHandle that
tools can query for `Record`s. Sources are pluggable: the registry lets
profiles declare `kind: "pcap"` or `kind: "log"` without the core knowing
about them.
"""

from traceweaver.core.source.base import (
    Record,
    Source,
    SourceHandle,
    SourceSpec,
)
from traceweaver.core.source.enrich import (
    Enricher,
    EnrichedSourceHandle,
    apply_enrichers,
)
from traceweaver.core.source.registry import SourceRegistry, get_default_registry

__all__ = [
    "EnrichedSourceHandle",
    "Enricher",
    "Record",
    "Source",
    "SourceHandle",
    "SourceRegistry",
    "SourceSpec",
    "apply_enrichers",
    "get_default_registry",
]
