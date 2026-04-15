from __future__ import annotations

from pathlib import Path
from typing import Sequence

from traceweaver.events import detect_events
from traceweaver.ingest.records import extract_5gc_records
from traceweaver.models import DetectedEventSet


def extract_5gc_events(
    path: str | Path,
    *,
    display_filter: str | None = None,
    decode_as: Sequence[str] | None = None,
    limit: int | None = None,
) -> DetectedEventSet:
    records = extract_5gc_records(
        path,
        display_filter=display_filter,
        decode_as=decode_as,
        limit=limit,
    )
    events = detect_events(records)
    return DetectedEventSet(
        path=records.path,
        file_name=records.file_name,
        event_count=len(events),
        warnings=list(records.warnings),
        events=events,
    )
