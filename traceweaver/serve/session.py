"""
Mutable capture session — allows tools to load pcaps at runtime.

The MCP server starts without a capture.  When the agent calls
``load_capture(path=...)`` the session swaps in a new SourceHandle
and all subsequent tool calls see the new data.
"""

from __future__ import annotations

from typing import Any, Iterator

from traceweaver.core.protocols import Record, SourceHandle


class CaptureSession:
    """Mutable wrapper that looks like a SourceHandle to tools.

    Tools access ``ctx.source_handle`` which points to this object.
    ``load_capture`` updates ``self._inner``; all tools immediately
    see the new data without any context rebuild.
    """

    def __init__(self) -> None:
        self._inner: SourceHandle | None = None
        self._capture_path: str | None = None

    # -- public ----------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._inner is not None

    @property
    def capture_path(self) -> str | None:
        return self._capture_path

    def load(self, handle: SourceHandle, path: str) -> None:
        self._inner = handle
        self._capture_path = path

    def unload(self) -> None:
        self._inner = None
        self._capture_path = None

    # -- SourceHandle proxy -----------------------------------------------

    def _require_inner(self) -> SourceHandle:
        if self._inner is None:
            raise RuntimeError(
                "No capture loaded. Call load_capture(path=...) first."
            )
        return self._inner

    def metadata(self) -> dict[str, Any]:
        return self._require_inner().metadata()

    def iter_records(
        self,
        *,
        filter: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[Record]:
        return self._require_inner().iter_records(
            filter=filter, fields=fields, limit=limit
        )

    def get_records_around(
        self, seq: int, *, before: int = 2, after: int = 2
    ) -> list[Record]:
        return self._require_inner().get_records_around(
            seq=seq, before=before, after=after
        )


__all__ = ["CaptureSession"]
