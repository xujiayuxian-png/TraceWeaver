"""
`get_tls_handshakes`: per-TCP-stream TLS handshake summary.

Synthesizes the wire pattern from individual `TLS_*` events into a
single per-handshake record:

    {
      flow_id, sni, client_hello_seq, server_hello_seq, finished_seq,
      alert_seq, alert_desc, terminated_by, status,
      handshake_types_seen, ciphersuite, supported_version
    }

`status` is the synthetic verdict the LLM should rely on:
    "completed"    : both sides reached `Finished`
    "alert"        : a plaintext TLS Alert was observed (TLS 1.2)
    "rst_mid_handshake"  : TCP RST after Client Hello but before Finished
    "incomplete"   : handshake started but capture ended before either
                     completion or termination
    "no_handshake" : the flow didn't actually do TLS

For TLS 1.3, the typical "cert expired / SNI mismatch" pcap signature
is "rst_mid_handshake" because alerts are encrypted on the wire.
"""

from __future__ import annotations

from typing import Any

from traceweaver.core.protocols import Tool, ToolContext, ToolResult, ToolSpec


def _classify(slot: dict[str, Any]) -> str:
    """Classify by what we observed on the wire.

    Order matters: a wire-failure signal (alert / RST mid-handshake)
    always wins over implicit completion. The `completed_likely_tls13`
    bucket exists because TLS 1.3 encrypts the Finished record, so a
    ServerHello followed by NO failure signal is the *normal* happy-path
    wire pattern for a successful TLS 1.3 connection.
    """
    if not slot["client_hello_seq"]:
        return "no_handshake"
    if slot["alert_seq"]:
        return "alert"
    if slot["rst_seq"]:
        return "rst_mid_handshake"
    if slot["finished_seq"]:
        return "completed"
    if slot["server_hello_seq"]:
        return "completed_likely_tls13"
    return "incomplete"


class GetTLSHandshakesTool(Tool):
    spec = ToolSpec(
        name="get_tls_handshakes",
        description=(
            "Summarize every TLS handshake observed (one entry per "
            "TCP stream that carried any TLS traffic). Each entry: "
            "`{flow_id, sni, client_hello_seq, server_hello_seq, "
            "finished_seq, alert_seq, alert_desc, rst_seq, status, "
            "handshake_types_seen, ciphersuite, supported_version}`. "
            "Status values: 'completed' (plaintext Finished seen, "
            "TLS 1.2), 'completed_likely_tls13' (ServerHello seen + no "
            "failure signal — TLS 1.3 happy path, since Finished is "
            "encrypted), 'alert' (plaintext alert), 'rst_mid_handshake' "
            "(TCP RST after ClientHello before any termination — typical "
            "TLS 1.3 cert/SNI failure wire signature), 'incomplete', "
            "'no_handshake'. Use to distinguish TLS-layer failures from "
            "L4 / L7 failures."
        ),
        parameters_schema={"type": "object", "properties": {}, "required": []},
    )

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.source_handle is None:
            return ToolResult(
                data={"handshakes": [], "count": 0, "hint": "no source_handle"},
            )

        # key: tcp.stream (int). DNS / UDP flows don't do TLS.
        slots: dict[int, dict[str, Any]] = {}

        for rec in ctx.source_handle.iter_records():
            f = rec.fields
            stream = f.get("tcp_stream")
            if not isinstance(stream, int):
                continue
            ev = f.get("event")
            ev_str = str(ev) if ev else None
            handshake_type = f.get("tls_handshake_type")
            alert_desc = f.get("tls_alert_desc")
            sni = f.get("tls_sni")
            cipher = f.get("tls.handshake.ciphersuite")
            supported_version = f.get("tls.handshake.extensions.supported_version")

            # Skip unrelated frames before we materialize a slot.
            relevant = (
                handshake_type is not None
                or alert_desc is not None
                or sni is not None
                or ev_str == "TCP_RST"
            )
            if not relevant and stream not in slots:
                continue

            slot = slots.setdefault(
                stream,
                {
                    "flow_id": f"tcp:{stream}",
                    "sni": None,
                    "client_hello_seq": None,
                    "server_hello_seq": None,
                    "certificate_seq": None,
                    "finished_seq": None,
                    "alert_seq": None,
                    "alert_desc": None,
                    "alert_level": None,
                    "rst_seq": None,
                    "rst_after_handshake_started": False,
                    "handshake_types_seen": [],
                    "ciphersuite": None,
                    "supported_version": None,
                },
            )

            if sni and slot["sni"] is None:
                slot["sni"] = sni
            if cipher and slot["ciphersuite"] is None:
                slot["ciphersuite"] = str(cipher)
            if supported_version and slot["supported_version"] is None:
                slot["supported_version"] = str(supported_version)

            if handshake_type is not None:
                if handshake_type not in slot["handshake_types_seen"]:
                    slot["handshake_types_seen"].append(handshake_type)
                if ev_str == "TLS_CLIENT_HELLO" and slot["client_hello_seq"] is None:
                    slot["client_hello_seq"] = rec.seq
                elif ev_str == "TLS_SERVER_HELLO" and slot["server_hello_seq"] is None:
                    slot["server_hello_seq"] = rec.seq
                elif ev_str == "TLS_CERTIFICATE" and slot["certificate_seq"] is None:
                    slot["certificate_seq"] = rec.seq
                elif ev_str == "TLS_FINISHED" and slot["finished_seq"] is None:
                    slot["finished_seq"] = rec.seq

            if alert_desc and slot["alert_seq"] is None:
                slot["alert_seq"] = rec.seq
                slot["alert_desc"] = str(alert_desc)
                slot["alert_level"] = f.get("tls_alert_level")

            if ev_str == "TCP_RST":
                # We only care about RSTs that arrived AFTER the handshake
                # started — an RST before any TLS frame is just a plain
                # TCP failure (will be reported by the TCP-side tools).
                if slot["client_hello_seq"] is not None and slot["rst_seq"] is None:
                    slot["rst_seq"] = rec.seq
                    slot["rst_after_handshake_started"] = True

        handshakes: list[dict[str, Any]] = []
        for stream, slot in sorted(slots.items()):
            handshakes.append(
                {
                    **slot,
                    "tcp_stream": stream,
                    "status": _classify(slot),
                }
            )

        data: dict[str, Any] = {
            "handshakes": handshakes,
            "count": len(handshakes),
        }
        if not handshakes:
            data["hint"] = (
                "no TLS handshakes found. The capture may be plain HTTP "
                "or DNS only — check `summarize_capture` first."
            )
        return ToolResult(data=data)


__all__ = ["GetTLSHandshakesTool"]
