"""
Source base types.

The shape of `Record` is fixed across all sources so that tools and the
kernel can stay source-agnostic. Source-specific columns live inside
`fields`; universal columns (timestamp, seq, key) are first-class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    """
    Unified raw record format (pcap / log / composed).

    - `source`    : one of "pcap" | "log" | "composed" | custom kind
    - `timestamp` : epoch seconds (float); used for time-window queries
    - `seq`       : source-local monotonic id (pcap frame.number,
                    log line number). Unique within one handle.
    - `key`       : correlation key (tcp.stream, trace_id, ngap UE id, ...).
                    Multiple records with the same key belong together.
    - `fields`    : protocol / structured fields extracted at ingest.
    - `raw`       : original line / info column (for display, not parsing).
    """

    model_config = ConfigDict(frozen=True)

    source: str
    timestamp: float
    seq: int
    key: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)
    raw: str = ""


class SourceSpec(BaseModel):
    """
    How to instantiate a Source. Normally built by a Profile from its
    `source_config` block, but users can construct one directly too.
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    uri: str
    options: dict[str, Any] = Field(default_factory=dict)


class SourceHandle(ABC):
    """
    Read-only handle over an already-ingested source.

    Implementations materialize records lazily when possible. The handle
    exposes the universal query primitives the kernel's built-in tools
    will call; source-specific behavior (e.g. extracting new tshark
    fields on demand) stays inside each implementation.
    """

    kind: str
    uri: str

    @abstractmethod
    def metadata(self) -> dict[str, Any]:
        """
        Return dataset-level summary: record count, time range, top-level
        statistics. Must be cheap (cached or O(n) at most).
        """

    @abstractmethod
    def iter_records(
        self,
        *,
        filter: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[Record]:
        """
        Yield records matching the (optional) filter.

        `filter` is a flat dict of equality constraints: keys can be
        top-level `Record` attributes (`source`, `seq`, `key`) or dotted
        paths into `Record.fields`. Implementations should treat unknown
        keys as "no match" (conservative).

        `fields` projects the returned `Record.fields` down to the named
        keys (useful for LLM context-window hygiene). Unknown projection
        keys are silently dropped.

        `limit`, if given, stops iteration after that many yields.
        """

    @abstractmethod
    def get_records_around(
        self,
        seq: int,
        *,
        before: int = 2,
        after: int = 2,
    ) -> list[Record]:
        """
        Return up to `before + 1 + after` records centered on `seq` (in
        seq order). Missing anchors (seq not in source) return the
        closest available window.
        """


class Source(ABC):
    """
    Source factory. Subclass once per kind ("pcap", "log", ...).
    """

    kind: str

    @abstractmethod
    def ingest(self, spec: SourceSpec) -> SourceHandle:
        """
        Turn a `SourceSpec` into a ready-to-query `SourceHandle`.

        Implementations should validate `spec.kind == self.kind` and
        raise `ValueError` otherwise. Heavy ingestion work (shelling
        out to tshark, parsing log files) happens here, not in
        `iter_records`.
        """


__all__ = ["Record", "Source", "SourceHandle", "SourceSpec"]
