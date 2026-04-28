# WebSocket close codes

RFC 6455 §7.4. Visible on the wire only when the closing peer sends a
**Close frame** (opcode 0x8) before tearing down the underlying TCP
connection.

## When you DON'T see a close code

The most diagnostically interesting failure mode is the absence of a
close frame: the TCP connection ends with **FIN or RST without any
preceding `WS_CLOSE` event**. This is the synthetic
`WS_CONNECTION_DROPPED` pattern. Causes include:

- **NAT/firewall idle timeout**: a stateful middlebox dropped the flow
  out of its connection table after N seconds of silence; subsequent
  TCP packets get RST'd. Fix: shorter WS keepalive (`ping` interval).
- **Load balancer worker recycling**: cloud LBs (HAProxy, ALB) reap
  long-lived backend connections on cron. Fix: configure session
  affinity + larger backend idle timeout.
- **Container OOM-kill**: server process died, kernel `RST`'d on its
  way out. Fix: examine server logs for OOM events.
- **Server crash**: same wire signature as OOM-kill but with a
  different root cause. Distinguished from logs.

## When you DO see a close code

| code     | name                      | meaning |
| -------- | ------------------------- | ------- |
| 1000     | Normal Closure            | Application finished cleanly. |
| 1001     | Going Away                | Endpoint is shutting down (e.g. browser tab close, server reboot). |
| 1002     | Protocol error            | Peer violated the WebSocket protocol. |
| 1003     | Unsupported Data          | Wrong frame type (e.g. text vs binary mismatch). |
| 1005     | No Status Rcvd (reserved) | Pseudo-code: peer closed without a status code. Never on the wire. |
| 1006     | Abnormal Closure (reserved)| Pseudo-code: TCP closed without WebSocket Close frame. **This is the lib-level rendering of `WS_CONNECTION_DROPPED`.** |
| 1007     | Invalid frame payload data| UTF-8 violation in a Text frame, etc. |
| 1008     | Policy Violation          | Server rejected the message for non-protocol reasons. |
| 1009     | Message Too Big           | Frame exceeded the receiver's max size. |
| 1010     | Mandatory Ext.            | Client required an extension the server doesn't support. |
| 1011     | Internal Error            | Server failed to handle the request (think 500). |
| 1012     | Service Restart           | Server is restarting, please reconnect. |
| 1013     | Try Again Later           | Backpressure / rate limit. |
| 1014     | Bad Gateway               | Upstream of the WS server gave a bad response. |
| 1015     | TLS Handshake (reserved)  | Pseudo-code: TLS layer failed; never sent on wire. |
| 4000-4999| Application-defined       | Application protocol's own codes. Read the app docs. |

## Wire-level frame structure

A Close frame (opcode 8) carries:

- 2-byte close code (network byte order) — visible as
  `websocket.close.code` if you ask tshark for it
- Optional UTF-8 reason string

The presence of `websocket.opcode == 8` BEFORE the TCP RST/FIN is the
signal that a graceful WebSocket close happened. Its absence is
itself the diagnosis.
