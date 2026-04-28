# Fixture follow-ups

## Known issue: `05_ws_idle_killed.pcapng` is incomplete

After the M6'.1 capture run the file is only 720 bytes and contains 4
DNS frames — no TCP SYN, no HTTP Upgrade, no RST. Root cause is
upstream of the docker-compose stack: `sleep 5 | websocat -t ws://...`
in the `nicolaka/netshoot` client container exits before issuing the
TCP `connect()`, so nothing is on the wire to capture.

This does NOT block writing `enrich.py` — the WS parsing logic can be
written and unit-tested separately, and the fixture can be re-cut once
the capture command is fixed.

### Hypotheses to test (in order of cheapness)

1. The `websocat -t` flag has changed meaning in some recent netshoot
   builds. Drop it: `sleep 5 | websocat ws://...`
2. `sleep 5` in busybox/alpine may interact badly with pipe semantics
   under `docker exec sh -c`. Replace with `tail -f /dev/null | websocat ...`
3. Bypass `websocat` entirely and use `curl` 7.86+ which speaks
   `ws://` natively when compiled with `--with-ws`. (Verify the
   netshoot `curl` has it: `curl -V | grep WS`.)
4. Ship a minimal Python ws client in the client container via
   `pip install --target` to a bind-mount, then run it with `python3`.

### Acceptance for the fix

The replayed `05_ws_idle_killed.pcapng` should contain:

- DNS A query/response for `ws-flaky.local`
- TCP three-way handshake to 8080
- HTTP GET with `Upgrade: websocket`
- HTTP 101 Switching Protocols response
- ≥ 1 WebSocket frame (any opcode)
- TCP RST from the server side (~3 s after handshake)

Total size ≥ 2 KB.

## Known limitation (by design): TLS 1.3 hides the Alert

`04_tls_cert_expired.pcapng` does NOT contain a plaintext TLS Alert
record. TLS 1.3 (which both curl and modern nginx default to)
encrypts post-handshake alerts inside application_data records, so
`tls.alert_message.desc` is unobtainable from the wire.

The `web_l4l7_failures` profile MUST therefore detect "TLS handshake
failed" from the wire pattern (Client Hello → Server Hello → ... →
TCP RST mid-handshake, no `tls.handshake.type=20` finished record on
the offending side), NOT from `tls.alert_message.desc`.

This is captured in the design doc and is the more general approach
anyway — TLS 1.3 will only become more prevalent.
