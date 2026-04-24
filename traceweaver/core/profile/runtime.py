"""
Runtime helpers that connect a `Profile` to the layered core
(Source + Enricher + KnowledgeStore).

Everything here has filesystem / import side effects, which is why it
lives outside `base.py` / `yaml_loader.py` (those two stay pure).

Primary entry point:
    ingest_for_profile(profile, source_spec, registry) -> SourceHandle

The returned handle is an `EnrichedSourceHandle` iff the profile
declares any enrichers; otherwise the raw inner handle is returned
unchanged so tests and M2 code keep working.
"""

from __future__ import annotations

import importlib
from typing import Callable

from traceweaver.core.protocols import KnowledgeStore, SourceHandle, SourceSpec
from traceweaver.core.profile.base import Profile, ProfileEnricherSpec
from traceweaver.core.source.registry import SourceRegistry

Enricher = Callable


def resolve_enrichers(specs: list[ProfileEnricherSpec]) -> list[Enricher]:
    """Import each `{module, function}` and return the callables."""
    resolved: list[Enricher] = []
    for spec in specs:
        try:
            mod = importlib.import_module(spec.module)
        except ImportError as exc:
            raise ImportError(
                f"cannot import enricher module {spec.module!r}: {exc}"
            ) from exc
        fn = getattr(mod, spec.function, None)
        if fn is None:
            raise AttributeError(
                f"enricher {spec.ref()!r}: module has no attribute "
                f"{spec.function!r}"
            )
        if not callable(fn):
            raise TypeError(f"enricher {spec.ref()!r} is not callable")
        resolved.append(fn)
    return resolved


def ingest_for_profile(
    profile: Profile,
    spec: SourceSpec,
    *,
    registry: SourceRegistry | None = None,
    extra_enrichers: list[Callable] | None = None,
) -> SourceHandle:
    """
    Build a SourceHandle for `spec` and wrap it with the profile's
    enrichers (if any). Callers that have already materialized a
    handle can use `wrap_handle_for_profile` instead.
    """
    if registry is None:
        raise ValueError("registry is required")
    inner = registry.build(spec)
    return wrap_handle_for_profile(
        profile, inner, extra_enrichers=extra_enrichers
    )


def wrap_handle_for_profile(
    profile: Profile,
    handle: SourceHandle,
    *,
    extra_enrichers: list[Callable] | None = None,
) -> SourceHandle:
    """
    Return `handle` possibly wrapped in `EnrichedSourceHandle`.

    `extra_enrichers` is mainly a test hook; profile-declared enrichers
    always come first so their invariants are preserved.
    """
    chain: list[Enricher] = list(resolve_enrichers(profile.enrichers))
    if extra_enrichers:
        chain.extend(extra_enrichers)
    if not chain:
        return handle
    from traceweaver.builtin.sources.enriched import EnrichedSourceHandle

    return EnrichedSourceHandle(handle, chain)


def build_knowledge_store(profile: Profile) -> KnowledgeStore | None:
    """
    Build a `FileKnowledgeStore` from the profile's declared knowledge
    items, or None if the profile has no knowledge.
    """
    if not profile.knowledge:
        return None
    from traceweaver.builtin.knowledge.file_store import FileKnowledgeStore

    return FileKnowledgeStore(items=list(profile.knowledge))


__all__ = [
    "build_knowledge_store",
    "ingest_for_profile",
    "resolve_enrichers",
    "wrap_handle_for_profile",
]
