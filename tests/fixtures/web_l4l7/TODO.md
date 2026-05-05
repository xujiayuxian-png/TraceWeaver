# Fixture follow-ups

## Known issue: `05_ws_idle_killed.pcapng` is incomplete

After the M6'.1 capture run the file is only 720 bytes and contains 4
DNS frames — no TCP SYN, no HTTP Upgrade, no RST. Root cause is
upstream of the docker-compose stack: `sleep 5 | websocat -t ws://...`
in the `nicolaka/netshoot` client container exits before issuing the
TCP `connect()`, so nothing is on the wire to capture.

**Fix applied**: `capture_all.sh` now uses `tail -f /dev/null | websocat -t ...`
instead of `sleep 5 | websocat -t ...`. The `sleep` command produces no
output so some shells close the pipe immediately, causing websocat to
see stdin EOF and exit before opening a TCP connection. `tail -f /dev/null`
keeps stdin open indefinitely.

**Next step**: Re-run `capture_all.sh` to regenerate `05_ws_idle_killed.pcapng`.
The pcap needs to be ≥ 2 KB and contain:
- DNS A query/response for `ws-flaky.local`
- TCP three-way handshake to 8080
- HTTP GET with `Upgrade: websocket`
- HTTP 101 Switching Protocols response
- ≥ 1 WebSocket frame (any opcode)
- TCP RST from the server side (~3 s after handshake)

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
