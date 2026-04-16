from __future__ import annotations

from typing import Sequence

from traceweaver.core.tshark.runner import run_checked

_field_catalog_cache: set[str] | None = None


def list_tshark_fields() -> set[str]:
    global _field_catalog_cache
    if _field_catalog_cache is not None:
        return _field_catalog_cache
    output = run_checked(["tshark", "-G", "fields"])
    available: set[str] = set()
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or parts[0] != "F":
            continue
        field_name = parts[2].strip()
        if field_name:
            available.add(field_name)
    _field_catalog_cache = available
    return available


def clear_tshark_field_cache() -> None:
    global _field_catalog_cache
    _field_catalog_cache = None


def resolve_field_aliases(
    field_specs: Sequence[tuple[str, Sequence[str]]],
) -> tuple[dict[str, str], list[str]]:
    available = list_tshark_fields()
    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for canonical, aliases in field_specs:
        actual = next((alias for alias in aliases if alias in available), None)
        if actual is None:
            unresolved.append(canonical)
            continue
        resolved[canonical] = actual
    return resolved, unresolved
