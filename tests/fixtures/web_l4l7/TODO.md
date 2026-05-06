# Fixture follow-ups

## ~~Known issue: `05_ws_idle_killed.pcapng` is incomplete~~ (FIXED)

**Root cause**: `sleep 5 | websocat -t ws://...` in the netshoot client
container exited before opening a TCP connection (sleep produces no
output, some shells close the pipe immediately).

**Fix applied**:
1. `capture_all.sh` now uses `curl ws://` (curl 8.18+ native WebSocket)
   instead of `websocat`. More reliable, no stdin pipe issues.
2. tshark capture writes to `/tmp` inside the container, then `docker cp`
   copies to the host volume mount. This avoids a permission denied issue
   where tshark (via dumpcap privilege dropping) cannot write directly to
   volume-mounted directories.

**Regenerated** (2026-05-06): `05_ws_idle_killed.pcapng` is now 2.7 KB
with full WebSocket handshake + server-side RST after ~3s idle.

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
