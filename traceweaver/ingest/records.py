from __future__ import annotations

from pathlib import Path
from typing import Sequence

from traceweaver.models import ExtractedRecordSet
from traceweaver.tshark.extract import extract_5gc_records as tshark_extract_5gc_records


def extract_5gc_records(
    path: str | Path,
    *,
    display_filter: str | None = None,
    decode_as: Sequence[str] | None = None,
    limit: int | None = None,
) -> ExtractedRecordSet:
    kwargs = {"decode_as": decode_as, "limit": limit}
    if display_filter is not None:
        kwargs["display_filter"] = display_filter
    return tshark_extract_5gc_records(path, **kwargs)
