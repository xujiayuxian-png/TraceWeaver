"""SourceRegistry: kind -> Source factory."""

from __future__ import annotations
from traceweaver.core.protocols import Source, SourceHandle, SourceSpec


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


__all__ = ["SourceRegistry"]
