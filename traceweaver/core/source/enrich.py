"""
Record enrichment (platform-v2 §4 Layer 0 + M3).

An `Enricher` is a pure function `Record -> Record`. Profiles declare a
list of enrichers in `profile.yaml:enrichers` (`{module, function}`
pairs) so the kernel can enrich every record before it reaches tools.

`EnrichedSourceHandle` wraps an underlying `SourceHandle`, applying
the enricher chain lazily on every `iter_records` / `get_records_around`
call. The wrapper exposes the same `SourceHandle` contract, so tools
are oblivious.

Design rules:
- Enrichers must NOT mutate the input Record; they return a new one
  (pydantic's `model_copy(update=...)` is the normal path).
- Enrichers are applied in declaration order (left-to-right); later
  ones see the output of earlier ones.
- Enrichers may add fields or recompute `key`, but MUST preserve
  `source`, `timestamp`, and `seq` verbatim (universal columns are
  the identity of a record).
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

from traceweaver.core.source.base import Record, SourceHandle


Enricher = Callable[[Record], Record]


def apply_enrichers(record: Record, enrichers: list[Enricher]) -> Record:
    """Run the chain; return the final Record."""
    for fn in enrichers:
        new_rec = fn(record)
        if new_rec.source != record.source or new_rec.seq != record.seq:
            raise RuntimeError(
                f"enricher {getattr(fn, '__qualname__', fn)!r} violated "
                "identity: (source, seq) must be preserved"
            )
        record = new_rec
    return record


class EnrichedSourceHandle(SourceHandle):
    """
    Lazy wrapper that runs `enrichers` on every record the inner handle
    yields. Metadata is pulled straight from the inner handle (enrichers
    don't change record counts).
    """

    def __init__(self, inner: SourceHandle, enrichers: list[Enricher]) -> None:
        self._inner = inner
        self._enrichers = list(enrichers)
        self.kind = inner.kind
        self.uri = inner.uri

    @property
    def inner(self) -> SourceHandle:
        return self._inner

    @property
    def enrichers(self) -> list[Enricher]:
        return list(self._enrichers)

    def metadata(self) -> dict[str, Any]:
        return self._inner.metadata()

    def iter_records(
        self,
        *,
        filter: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[Record]:
        # If filter or fields are provided, we must enrich BEFORE we
        # match / project — enrichment commonly creates the very fields
        # that callers filter on (e.g. the 5GC `event` derived field).
        has_filter = bool(filter)
        proj = list(fields) if fields else None

        emitted = 0
        # Ask the inner handle for unfiltered, unprojected records; do
        # filtering and projection here against the enriched output.
        for rec in self._inner.iter_records():
            enriched = apply_enrichers(rec, self._enrichers)
            if has_filter and not _match(enriched, filter or {}):
                continue
            if proj is not None:
                enriched = _project(enriched, proj)
            yield enriched
            emitted += 1
            if limit is not None and emitted >= limit:
                return

    def get_records_around(
        self, seq: int, *, before: int = 2, after: int = 2
    ) -> list[Record]:
        window = self._inner.get_records_around(seq, before=before, after=after)
        return [apply_enrichers(r, self._enrichers) for r in window]


# ---- local copies of the fake/pcap handles' match/project helpers ----
# Kept private so enrichment doesn't reach into those modules.

def _match(record: Record, flt: dict[str, Any]) -> bool:
    for key, want in flt.items():
        got: Any
        if key in {"source", "timestamp", "seq", "key", "raw"}:
            got = getattr(record, key)
        else:
            got = record.fields.get(key)
        if got != want:
            return False
    return True


def _project(record: Record, fields: list[str]) -> Record:
    keep = {k: v for k, v in record.fields.items() if k in set(fields)}
    return record.model_copy(update={"fields": keep})


__all__ = ["Enricher", "EnrichedSourceHandle", "apply_enrichers"]
