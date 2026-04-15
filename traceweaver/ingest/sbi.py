from __future__ import annotations

from pathlib import Path
from typing import Sequence

from traceweaver.correlate.sbi import pair_sbi_calls
from traceweaver.ingest.records import extract_5gc_records
from traceweaver.models import SBICallSet


def extract_sbi_calls(
    path: str | Path,
    *,
    display_filter: str | None = None,
    decode_as: Sequence[str] | None = None,
    limit: int | None = None,
) -> SBICallSet:
    records = extract_5gc_records(
        path,
        display_filter=display_filter,
        decode_as=decode_as,
        limit=limit,
    )
    calls = pair_sbi_calls(records)
    return SBICallSet(
        path=records.path,
        file_name=records.file_name,
        call_count=len(calls),
        warnings=list(records.warnings),
        calls=calls,
    )
