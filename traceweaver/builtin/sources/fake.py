"""FakeSource: in-memory source backed by a pre-built list of Records."""
from __future__ import annotations
from bisect import bisect_left
from typing import Any, Iterator
from traceweaver.core.protocols import Record, Source, SourceHandle, SourceSpec

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

def _project(record: Record, fields: list[str] | None) -> Record:
    if fields is None:
        return record
    keep = {k: v for k, v in record.fields.items() if k in set(fields)}
    return record.model_copy(update={"fields": keep})

class FakeSourceHandle(SourceHandle):
    kind = "fake"
    def __init__(self, uri: str, records: list[Record]) -> None:
        self.uri = uri
        self._records = sorted(records, key=lambda r: r.seq)
        self._seqs = [r.seq for r in self._records]

    def metadata(self) -> dict[str, Any]:
        if not self._records:
            return {"count": 0, "time_range": None}
        return {"count": len(self._records), "time_range": [self._records[0].timestamp, self._records[-1].timestamp], "seq_range": [self._records[0].seq, self._records[-1].seq]}

    def iter_records(self, *, filter=None, fields=None, limit=None) -> Iterator[Record]:
        emitted = 0
        for r in self._records:
            if filter and not _match(r, filter):
                continue
            yield _project(r, fields)
            emitted += 1
            if limit is not None and emitted >= limit:
                return

    def get_records_around(self, seq: int, *, before=2, after=2) -> list[Record]:
        if not self._records:
            return []
        idx = bisect_left(self._seqs, seq)
        lo = max(0, idx - before)
        hi = min(len(self._records), idx + after + 1)
        return list(self._records[lo:hi])

class FakeSource(Source):
    kind = "fake"
    def ingest(self, spec: SourceSpec) -> SourceHandle:
        if spec.kind != self.kind:
            raise ValueError(f"FakeSource cannot ingest kind={spec.kind!r}")
        records_raw = spec.options.get("records_object")
        if records_raw is not None:
            records = list(records_raw)
        else:
            records = [Record(**r) for r in spec.options.get("records", [])]
        return FakeSourceHandle(uri=spec.uri, records=records)

__all__ = ["FakeSource", "FakeSourceHandle"]
