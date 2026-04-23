"""Record enrichment wrapper."""
from __future__ import annotations
from typing import Any, Callable, Iterator
from traceweaver.core.protocols import Record, SourceHandle

Enricher = Callable[[Record], Record]

_FORBIDDEN = frozenset({"verdict", "root_cause", "failure_point", "confidence"})

def apply_enrichers(record: Record, enrichers: list[Enricher]) -> Record:
    for fn in enrichers:
        new_rec = fn(record)
        if new_rec.source != record.source or new_rec.seq != record.seq:
            raise RuntimeError(f"enricher {getattr(fn, '__qualname__', fn)!r} violated identity")
        forbidden = _FORBIDDEN & set(new_rec.fields.keys())
        if forbidden:
            raise RuntimeError(f"enricher {getattr(fn, '__qualname__', fn)!r} produced forbidden: {sorted(forbidden)}")
        record = new_rec
    return record

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

class EnrichedSourceHandle(SourceHandle):
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

    def iter_records(self, *, filter=None, fields=None, limit=None) -> Iterator[Record]:
        has_filter = bool(filter)
        proj = list(fields) if fields else None
        emitted = 0
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

    def get_records_around(self, seq: int, *, before=2, after=2) -> list[Record]:
        window = self._inner.get_records_around(seq, before=before, after=after)
        return [apply_enrichers(r, self._enrichers) for r in window]

__all__ = ["Enricher", "EnrichedSourceHandle", "apply_enrichers"]
