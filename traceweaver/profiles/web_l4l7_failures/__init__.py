"""
web_l4l7_failures: TraceWeaver's second reference profile.

Covers the L4-L7 connection-level failure modes a backend / ops engineer
hits day-to-day, **without** requiring TLS decryption:

    DNS  : NXDOMAIN / SERVFAIL / unanswered queries / wrong NS
    TCP  : RST / SYN never answered / port unreachable
    TLS  : handshake aborted (cert expired / SNI mismatch / cipher)
    WS   : abnormal disconnect (no Close frame, server-side abort)

Package contents:
- `fields`     : canonical tshark field names + event constant maps
                 (DNS rcode → event, TLS handshake type → event,
                 WS opcode → event, TCP flag bits → name).
- `enrich`     : record enricher; derives `event`, `protocol_layer`,
                 `flow_id`, normalized cause/alert/rcode fields.
- `tools/`     : six tools exposed to the LLM (summarize_capture,
                 list_flows, get_flow_timeline, get_dns_queries,
                 get_tls_handshakes, get_records_around).
- `knowledge/` : DNS rcodes / TCP termination / TLS alerts / WS close
                 codes — reference docs the LLM can search.

The actual profile is declared in `profile.yaml` alongside this module;
`traceweaver analyze --profile web_l4l7_failures` resolves here.

Design doc: docs/design/profile-web_l4l7_failures.md
Test fixture (pcaps + docker-compose): tests/fixtures/web_l4l7/
"""
