# TCP termination patterns

How a TCP flow ends carries most of the diagnostic signal in this
profile. The four wire patterns to recognize:

## 1. Graceful close (FIN/ACK on both sides)

```
A → B  FIN, ACK     # tcp.flags = 0x011
B → A  ACK          # tcp.flags = 0x010
B → A  FIN, ACK     # tcp.flags = 0x011
A → B  ACK          # tcp.flags = 0x010
```

Both sides agreed to stop. Application layer typically already finished
its work. **Not a failure.**

## 2. RST mid-flight (TCP_RST)

```
A → B  ...data...
B → A  RST, ACK     # tcp.flags = 0x014  (the moment of truth)
```

Server (or middlebox) decided to abort the connection. Cause is
**not** in the RST frame itself — you need to look at:

- **What was the client just doing?** RST right after a `TLS Client
  Hello` typically means SNI rejected by the load balancer / no
  matching virtual host. RST right after `HTTP GET` typically means
  the server crashed mid-request or the L7 firewall rejected the URL.
- **Who sent the RST?** If `dst_ip` is the *client*, the *server*
  refused. Vice versa.
- **Is there a retransmit count climbing first?** A handful of
  retransmits followed by RST is "TCP keepalive timed out the dead
  peer" — the L4 path is broken, not the application.

## 3. Refused connection (TCP_RST without preceding data)

```
A → B  SYN          # tcp.flags = 0x002
B → A  RST, ACK     # tcp.flags = 0x014   ← right back, no SYN+ACK first
```

Kernel-level rejection: **no process listening on that port**, or an
explicit `iptables -j REJECT --reject-with tcp-reset`. The application
on B never even saw the connection attempt.

## 4. SYN never answered (TCP_CONNECTION_FAILED, synthetic)

```
A → B  SYN          # tcp.flags = 0x002
A → B  SYN          # retransmit ~1s later
A → B  SYN          # retransmit ~3s later
... no SYN+ACK ever arrives ...
```

The packet was dropped (firewall `-j DROP`, or the host is down).
Distinguishable from #3 by the **silence** on the return path. This
is a synthetic event — the enricher emits no `event` for the
retransmits per se; the tool layer joins SYN frames against
SYN+ACK frames per `tcp.stream` to detect the unanswered case.

## TCP flag bit cheat sheet

| bit  | hex   | meaning |
| ---- | ----- | ------- |
| FIN  | 0x01  | Initiator wants to close. |
| SYN  | 0x02  | Initiating a new connection (or its half). |
| RST  | 0x04  | Hard abort — no graceful close. |
| PSH  | 0x08  | Push data to application immediately. |
| ACK  | 0x10  | Acknowledgement number is meaningful. |

Common combinations the enricher recognizes:

| flags  | hex     | name in this profile |
| ------ | ------- | -------------------- |
| SYN    | 0x002   | TCP_SYN              |
| SYN+ACK| 0x012   | TCP_SYN_ACK          |
| FIN+ACK| 0x011   | TCP_FIN              |
| RST    | 0x004   | TCP_RST              |
| RST+ACK| 0x014   | TCP_RST              |
| ACK    | 0x010   | (no event)           |
