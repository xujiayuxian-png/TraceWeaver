"""Shared fixtures for the web_l4l7_failures profile tests.

The factory style here is deliberately different from
`tests/profiles/open5gs_5gc/conftest.py`: that profile has ~10 named
fields so per-field kwargs are readable; this profile has ~30, so we
take a flat `fields` dict instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from traceweaver.builtin.sources.enriched import EnrichedSourceHandle
from traceweaver.builtin.sources.fake import FakeSource
from traceweaver.core.profile import Profile
from traceweaver.core.profile.yaml_loader import load_profile_from_dir
from traceweaver.core.protocols import Record, SourceSpec


PROFILE_ROOT = (
    Path(__file__).resolve().parents[3] / "traceweaver" / "profiles" / "web_l4l7_failures"
)


@pytest.fixture(scope="module")
def profile() -> Profile:
    return load_profile_from_dir(PROFILE_ROOT)


def make_record(
    seq: int,
    fields: dict[str, Any],
    *,
    timestamp: float | None = None,
) -> Record:
    """Build a raw tshark-shaped record with the given field map."""
    return Record(
        source="pcap",
        timestamp=timestamp if timestamp is not None else 1_700_000_000.0 + seq * 0.01,
        seq=seq,
        key="",
        fields=dict(fields),
    )


@pytest.fixture()
def enriched_handle():
    """Build an EnrichedSourceHandle wrapping in-memory raw records."""
    from traceweaver.profiles.web_l4l7_failures.enrich import enrich

    def _build(records: list[Record]) -> EnrichedSourceHandle:
        inner = FakeSource().ingest(
            SourceSpec(
                kind="fake",
                uri="memory://t",
                options={"records_object": records},
            )
        )
        return EnrichedSourceHandle(inner, [enrich])

    return _build
