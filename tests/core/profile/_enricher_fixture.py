"""Test fixture module imported by profile runtime tests."""

from __future__ import annotations

from traceweaver.core.source import Record


NOT_CALLABLE = 42


def add_hi(record: Record) -> Record:
    new_fields = dict(record.fields)
    new_fields["hi"] = "there"
    return record.model_copy(update={"fields": new_fields})
