"""
`get_dns_queries`: DNS query/response join, per-name + per-rcode stats.

Web l4l7 captures routinely contain multiple DNS transactions per name
(Linux glibc resolver fires A and AAAA in parallel; an A→NOERROR plus
AAAA→NXDOMAIN for the same name is normal, not a failure). The LLM
should not have to perform this join manually — this tool does it.

Output:
    queries: per-(qname, qtype) summary with the rcode of the matched
             response, or `unanswered: true` if no response was seen.
    by_name: per-qname rollup that hides the qtype detail and surfaces
             the operationally-meaningful "any answer ok?" boolean.
    rcode_mix: capture-wide rcode histogram.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec


class GetDNSQueriesTool(Tool):
    spec = ToolSpec(
        name="get_dns_queries",
        description=(
            "Join DNS queries with their responses by `dns.id` + qtype, "
            "and surface per-name rollups. Each entry in `queries` has "
            "`{dns_id, qname, qtype, qtype_name, query_seq, response_seq, "
            "rcode, rcode_name, unanswered}`. `by_name` aggregates across "
            "qtypes per qname (`{qname, ok_response_count, "
            "nxdomain_count, servfail_count, refused_count, "
            "other_failure_count, unanswered_count, any_ok}`). "
            "`rcode_mix` is the capture-wide histogram. Linux glibc "
            "fires parallel A + AAAA queries — a single name with one "
            "ok and one nxdomain (because no AAAA record) is NORMAL."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "qname_contains": {
                    "type": "string",
                    "description": (
                        "Substring filter applied to qname (case-insensitive). "
                        "Useful when the capture has many distinct names."
                    ),
                },
            },
            "required": [],
        },
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={"queries": [], "by_name": [], "rcode_mix": {}, "hint": "no source_handle"},
            )

        qname_filter = kwargs.get("qname_contains")
        if qname_filter is not None and not isinstance(qname_filter, str):
            qname_filter = None
        qname_filter_lower = qname_filter.lower() if qname_filter else None

        # key: (dns_id, qname, qtype) — the qname+qtype is needed because
        # different transactions may reuse a dns_id over time.
        transactions: dict[tuple[Any, str, int | None], dict[str, Any]] = {}

        for rec in ctx.source_handle.iter_records():
            f = rec.fields
            dns_id = f.get("dns_id")
            qname = f.get("dns_qname")
            qtype = f.get("dns_qtype")
            if dns_id is None or qname is None:
                continue
            qname_str = str(qname)
            if qname_filter_lower and qname_filter_lower not in qname_str.lower():
                continue
            key = (dns_id, qname_str, qtype)
            slot = transactions.setdefault(
                key,
                {
                    "dns_id": dns_id,
                    "qname": qname_str,
                    "qtype": qtype,
                    "qtype_name": f.get("dns_qtype_name"),
                    "query_seq": None,
                    "response_seq": None,
                    "rcode": None,
                    "rcode_name": None,
                },
            )
            is_resp = f.get("dns_is_response")
            if is_resp is True:
                if slot["response_seq"] is None:
                    slot["response_seq"] = rec.seq
                    slot["rcode"] = f.get("dns_rcode")
                    slot["rcode_name"] = f.get("dns_rcode_name")
            else:
                if slot["query_seq"] is None:
                    slot["query_seq"] = rec.seq

        # Build the per-transaction list.
        queries: list[dict[str, Any]] = []
        for slot in sorted(
            transactions.values(),
            key=lambda s: (s["query_seq"] if s["query_seq"] is not None else s["response_seq"] or 0),
        ):
            queries.append(
                {
                    **slot,
                    "unanswered": slot["response_seq"] is None,
                }
            )

        # Per-qname rollup.
        by_name_slots: dict[str, dict[str, Any]] = {}
        for q in queries:
            name = q["qname"]
            slot = by_name_slots.setdefault(
                name,
                {
                    "qname": name,
                    "ok_response_count": 0,
                    "nxdomain_count": 0,
                    "servfail_count": 0,
                    "refused_count": 0,
                    "other_failure_count": 0,
                    "unanswered_count": 0,
                    "any_ok": False,
                },
            )
            if q["unanswered"]:
                slot["unanswered_count"] += 1
                continue
            rcode = q["rcode"]
            if rcode == 0:
                slot["ok_response_count"] += 1
                slot["any_ok"] = True
            elif rcode == 3:
                slot["nxdomain_count"] += 1
            elif rcode == 2:
                slot["servfail_count"] += 1
            elif rcode == 5:
                slot["refused_count"] += 1
            else:
                slot["other_failure_count"] += 1

        by_name = sorted(by_name_slots.values(), key=lambda s: s["qname"])

        # Rcode histogram (capture-wide).
        rcode_mix: Counter[str] = Counter()
        for q in queries:
            if q["rcode_name"]:
                rcode_mix[str(q["rcode_name"])] += 1
            elif q["unanswered"]:
                rcode_mix["UNANSWERED"] += 1

        data: dict[str, Any] = {
            "queries": queries,
            "by_name": by_name,
            "rcode_mix": dict(rcode_mix),
            "filter": {"qname_contains": qname_filter},
        }
        if not queries:
            data["hint"] = (
                "no DNS transactions found"
                + (f" matching qname_contains={qname_filter!r}" if qname_filter else "")
                + ". Try `summarize_capture` to confirm the capture has DNS at all."
            )
        return ToolResult(data=data)


__all__ = ["GetDNSQueriesTool"]
