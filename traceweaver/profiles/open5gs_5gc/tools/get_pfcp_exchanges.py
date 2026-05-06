"""
`get_pfcp_exchanges`: list PFCP messages between SMF and UPF.

Groups raw PFCP frames by SEID where possible so the LLM sees one
logical session per entry instead of N individual frames.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec


_DEFAULT_LIMIT = 50
_MAX_LIMIT = 300


class _GetPFCPExchangesInput(BaseModel):
    msg_name_contains: str | None = Field(default=None)
    seid: str | None = Field(default=None)
    limit: int = Field(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT)


class GetPFCPExchangesTool(Tool):
    spec = ToolSpec.from_pydantic(
        _GetPFCPExchangesInput,
        name="get_pfcp_exchanges",
        description=(
            "List PFCP messages observed between SMF and UPF. Each entry "
            "has `{seq, timestamp, msg_type, msg_name, seid, cause, "
            "src_ip, dst_ip}`. Filter with `msg_name_contains` "
            "(case-insensitive, matches SESSION_ESTABLISHMENT, MODIFICATION, "
            "DELETION, HEARTBEAT, etc.) or `seid` for a specific session."
        ),
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={"exchanges": [], "count": 0, "hint": "no source_handle"},
            )

        needle = (kwargs.get("msg_name_contains") or "").upper() or None
        seid_wanted = kwargs.get("seid")
        if seid_wanted in (None, ""):
            seid_wanted = None
        else:
            seid_wanted = str(seid_wanted)
        try:
            limit = int(kwargs.get("limit") or _DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT
        limit = max(1, min(limit, _MAX_LIMIT))

        rows: list[dict[str, Any]] = []
        for rec in ctx.source_handle.iter_records():
            f = rec.fields
            msg_type = f.get("pfcp_msg_type")
            if msg_type is None:
                continue
            msg_name = f.get("pfcp_msg_name") or ""
            if needle and needle not in msg_name.upper():
                continue
            seid = f.get("pfcp.seid")
            if seid_wanted is not None and str(seid or "") != seid_wanted:
                continue
            rows.append(
                {
                    "seq": rec.seq,
                    "timestamp": rec.timestamp,
                    "msg_type": msg_type,
                    "msg_name": msg_name or None,
                    "seid": seid,
                    "cause": f.get("pfcp.cause"),
                    "src_ip": f.get("src_ip"),
                    "dst_ip": f.get("dst_ip"),
                }
            )
            if len(rows) >= limit:
                break

        data: dict[str, Any] = {"exchanges": rows, "count": len(rows)}
        if not rows:
            data["hint"] = (
                "no PFCP messages matched. If the capture is radio-only "
                "(gNB<->AMF), PFCP will be absent; don't keep retrying."
            )
        return ToolResult(data=data)


__all__ = ["GetPFCPExchangesTool"]
