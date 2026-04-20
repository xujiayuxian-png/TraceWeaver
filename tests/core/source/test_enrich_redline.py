"""
Test enricher red line: forbidden judgment fields.
"""
from __future__ import annotations

import pytest

from traceweaver.core.source.base import Record, SourceHandle
from traceweaver.core.source.enrich import (
    _FORBIDDEN_ENRICH_KEYS,
    apply_enrichers,
)


def _make_record(fields: dict | None = None) -> Record:
    return Record(
        source="test",
        timestamp=0.0,
        seq=1,
        key="k",
        raw="",
        fields=fields or {},
    )


def test_forbidden_keys_list():
    """Verify the forbidden set covers all judgment fields."""
    assert "verdict" in _FORBIDDEN_ENRICH_KEYS
    assert "root_cause" in _FORBIDDEN_ENRICH_KEYS
    assert "failure_point" in _FORBIDDEN_ENRICH_KEYS
    assert "confidence" in _FORBIDDEN_ENRICH_KEYS


def test_enricher_with_forbidden_field_raises():
    """Enricher producing forbidden fields must raise RuntimeError."""

    def bad_enricher(r: Record) -> Record:
        return r.model_copy(update={"fields": {**r.fields, "verdict": "failure"}})

    rec = _make_record()
    with pytest.raises(RuntimeError) as exc_info:
        apply_enrichers(rec, [bad_enricher])
    assert "verdict" in str(exc_info.value)
    assert "forbidden" in str(exc_info.value).lower()


def test_enricher_with_root_cause_raises():
    """Enricher producing root_cause must raise."""

    def bad_enricher(r: Record) -> Record:
        return r.model_copy(update={"fields": {**r.fields, "root_cause": "timeout"}})

    rec = _make_record()
    with pytest.raises(RuntimeError) as exc_info:
        apply_enrichers(rec, [bad_enricher])
    assert "root_cause" in str(exc_info.value)


def test_enricher_with_multiple_forbidden_raises():
    """Enricher producing multiple forbidden fields reports all."""

    def bad_enricher(r: Record) -> Record:
        return r.model_copy(
            update={"fields": {**r.fields, "verdict": "failure", "confidence": 0.9}}
        )

    rec = _make_record()
    with pytest.raises(RuntimeError) as exc_info:
        apply_enrichers(rec, [bad_enricher])
    msg = str(exc_info.value)
    assert "verdict" in msg
    assert "confidence" in msg


def test_valid_enricher_passes():
    """Enricher producing allowed fields should work."""

    def good_enricher(r: Record) -> Record:
        return r.model_copy(update={"fields": {**r.fields, "event": "REGISTRATION_REQUEST"}})

    rec = _make_record()
    result = apply_enrichers(rec, [good_enricher])
    assert result.fields["event"] == "REGISTRATION_REQUEST"


def test_allowed_cause_fields_pass():
    """Cause code fields (mm_cause, sm_cause) are allowed."""

    def cause_enricher(r: Record) -> Record:
        return r.model_copy(update={"fields": {**r.fields, "mm_cause": "#3", "sm_cause": "#28"}})

    rec = _make_record()
    result = apply_enrichers(rec, [cause_enricher])
    assert result.fields["mm_cause"] == "#3"
    assert result.fields["sm_cause"] == "#28"
