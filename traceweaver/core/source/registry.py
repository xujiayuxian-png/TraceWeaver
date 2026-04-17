"""
SourceRegistry: kind -> Source factory.

A tiny indirection so profiles can declare `kind: "pcap"` in YAML and
have the kernel resolve that to the right Source class at ingest time.
"""

from __future__ import annotations

from traceweaver.core.source.base import Source, SourceHandle, SourceSpec


class SourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}

    def register(self, source: Source) -> None:
        if source.kind in self._sources:
            raise ValueError(f"source kind already registered: {source.kind}")
        self._sources[source.kind] = source

    def has(self, kind: str) -> bool:
        return kind in self._sources

    def kinds(self) -> list[str]:
        return list(self._sources.keys())

    def build(self, spec: SourceSpec) -> SourceHandle:
        if spec.kind not in self._sources:
            raise KeyError(
                f"unknown source kind: {spec.kind} "
                f"(registered: {sorted(self._sources.keys())})"
            )
        return self._sources[spec.kind].ingest(spec)


_DEFAULT_REGISTRY: SourceRegistry | None = None


def get_default_registry() -> SourceRegistry:
    """
    Lazy-initialized process-wide registry pre-populated with the
    built-in sources. The registry is mutable; tests and extensions
    can add custom kinds.
    """
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        reg = SourceRegistry()
        from traceweaver.core.source.fake import FakeSource
        from traceweaver.core.source.pcap import PcapSource

        reg.register(FakeSource())
        reg.register(PcapSource())
        _DEFAULT_REGISTRY = reg
    return _DEFAULT_REGISTRY


__all__ = ["SourceRegistry", "get_default_registry"]
