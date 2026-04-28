"""
End-to-end smoke for the `web_l4l7_failures` profile.

Loads the profile, ingests each of the 5 canonical pcaps, runs them
through the enricher, and prints the resulting event timeline. Use
this as a "did I break the wire interpretation?" sanity check after
touching `fields.py` or `enrich.py`.

Requires `tshark` on PATH. On Windows, that usually means:

    $env:PATH += ";C:\\Program Files\\Wireshark"
    .venv\\Scripts\\python scripts\\smoke_web_l4l7_profile.py

Exits 0 if every pcap was ingested without an exception. Does NOT
verify the *content* of events — that's done by unit tests in
`tests/profiles/web_l4l7_failures/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from traceweaver.builtin.sources.enriched import EnrichedSourceHandle
from traceweaver.builtin.sources.pcap import PcapSource
from traceweaver.core.profile import ProfileLoader
from traceweaver.core.profile.runtime import resolve_enrichers
from traceweaver.core.protocols import SourceSpec, ToolContext
from traceweaver.core.tools.loader import load_profile_tools
from traceweaver.core.tools.registry import ToolRegistry


REPO_ROOT = Path(__file__).resolve().parent.parent
PCAP_DIR = REPO_ROOT / "tests" / "fixtures" / "web_l4l7" / "pcaps"


def _ingest(pcap_path: Path, profile) -> EnrichedSourceHandle:
    source = PcapSource()
    source_cfg = profile.source_config["pcap"]
    spec = SourceSpec(
        kind="pcap",
        uri=str(pcap_path),
        options={
            "fields": list(source_cfg.get("fields", [])),
            "display_filter": source_cfg.get("display_filter"),
            "key_strategy": source_cfg.get("key_strategy"),
        },
    )
    inner = source.ingest(spec)
    enrichers = resolve_enrichers(profile.enrichers)
    return EnrichedSourceHandle(inner, enrichers)


def _summarize(name: str, handle: EnrichedSourceHandle) -> int:
    events: list[tuple[int, str, str | None, str | None]] = []
    total = 0
    for rec in handle.iter_records():
        total += 1
        ev = rec.fields.get("event")
        layer = rec.fields.get("protocol_layer")
        flow = rec.fields.get("flow_id")
        if ev:
            events.append((rec.seq, ev, layer, flow))

    print(f"\n=== {name} ({total} frames) ===")
    if not events:
        print("  (no events)")
        return total
    for seq, ev, layer, flow in events:
        flow_str = flow if flow else "-"
        print(f"  seq={seq:<4} layer={layer:<10} flow={flow_str:<10} event={ev}")
    return total


def _exercise_tools(handle: EnrichedSourceHandle, registry: ToolRegistry) -> None:
    """Run the profile's read-only tools against the handle and print the
    high-level signals each one returns. Catches any exception so a single
    broken tool doesn't halt the whole smoke."""
    ctx = ToolContext(source_handle=handle)
    summary_signals = None
    for tool_name in ("summarize_capture", "list_flows", "get_dns_queries", "get_tls_handshakes"):
        tool = registry.get(tool_name)
        try:
            result = tool.run(ctx)
        except Exception as exc:
            print(f"    {tool_name}: ERROR {exc!r}")
            continue
        data = result.data
        if tool_name == "summarize_capture":
            summary_signals = data["capture_signals"]
            sig_keys = ("flow_count", "dns_nxdomain_count", "tcp_rst_count",
                        "tls_handshake_started_count", "tls_handshake_completed_count",
                        "tls_handshake_failed_count", "ws_abnormal_disconnect_count")
            sig = {k: summary_signals.get(k) for k in sig_keys}
            print(f"    summarize_capture.signals: {sig}")
        elif tool_name == "list_flows":
            ids = [f["flow_id"] for f in data["flows"]]
            print(f"    list_flows: {len(ids)} flows -> {ids}")
        elif tool_name == "get_dns_queries":
            print(f"    get_dns_queries: rcode_mix={data['rcode_mix']}")
            for entry in data["by_name"]:
                print(f"      {entry['qname']}: any_ok={entry['any_ok']} "
                      f"nx={entry['nxdomain_count']} ok={entry['ok_response_count']}")
        elif tool_name == "get_tls_handshakes":
            for hs in data["handshakes"]:
                print(f"    tls handshake on {hs['flow_id']}: status={hs['status']} "
                      f"sni={hs['sni']!r} alert_desc={hs['alert_desc']!r}")


def main() -> int:
    if not PCAP_DIR.is_dir():
        print(f"[smoke] FAIL: {PCAP_DIR} not found", file=sys.stderr)
        return 1

    pcaps = sorted(PCAP_DIR.glob("*.pcapng"))
    if not pcaps:
        print(f"[smoke] FAIL: no *.pcapng under {PCAP_DIR}", file=sys.stderr)
        return 1

    loader = ProfileLoader()
    profile = loader.load("web_l4l7_failures")
    print(f"[smoke] loaded profile: {profile.name}")

    registry = ToolRegistry()
    tool_names = load_profile_tools(registry, profile.tools)
    print(f"[smoke] loaded tools: {tool_names}")

    failures = []
    for p in pcaps:
        try:
            handle = _ingest(p, profile)
            _summarize(p.name, handle)
            _exercise_tools(handle, registry)
        except Exception as exc:  # pragma: no cover
            print(f"\n=== {p.name} ===")
            print(f"  ERROR: {exc}", file=sys.stderr)
            failures.append((p.name, exc))

    if failures:
        print(f"\n[smoke] FAIL: {len(failures)} pcap(s) errored", file=sys.stderr)
        return 1

    print(f"\n[smoke] OK: {len(pcaps)} pcap(s) ingested + enriched without error")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
