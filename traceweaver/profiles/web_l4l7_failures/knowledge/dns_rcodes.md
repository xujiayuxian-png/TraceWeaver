# DNS Response Codes (RCODE)

RFC 1035 + RFC 6895. Visible in tshark as `dns.flags.rcode`.

| code | name      | meaning |
| ---- | --------- | ------- |
| 0    | NOERROR   | Query succeeded. The answer section may still be empty (`ANCOUNT=0`) for legitimate empty responses. |
| 1    | FORMERR   | The server could not interpret the query. Almost always a client-side encoding bug. |
| 2    | SERVFAIL  | Server-side failure: upstream timeout, DNSSEC validation error, broken zone, or process crashed. **Most operationally important** — a SERVFAIL on a name that *should* resolve usually means the resolver itself or its upstream is sick. |
| 3    | NXDOMAIN  | The name authoritatively does not exist. From a *configured* zone this is dispositive; from an unknown TLD it can also indicate the resolver has no upstream. |
| 4    | NOTIMP    | Server does not implement the requested op. Rare. |
| 5    | REFUSED   | Server refused to answer. Often means the resolver thinks the client isn't allowed to query, or the resolver has no path to the zone (no upstream + not authoritative). |
| 6    | YXDOMAIN  | Name should not exist but does (dynamic DNS update). |
| 7    | YXRRSET   | RR set should not exist but does. |
| 8    | NXRRSET   | RR set should exist but does not (dynamic update prerequisite). |
| 9    | NOTAUTH   | Server is not authoritative for the zone, or DNS Update key not authorized. |
| 10   | NOTZONE   | Name not contained in zone. |

## Failure-mode quick reference

- **Glibc dual-stack quirk**: Linux clients fire **A and AAAA queries
  in parallel** for the same name. If your zone only has A records the
  AAAA query returns `NXDOMAIN` (rcode=3) — this is **noise**, not a
  failure, as long as the A response is `NOERROR`. When diagnosing,
  always join responses by `dns.id` + `dns.qry.type`.
- **Unanswered query** (synthetic): if a `DNS_QUERY` frame appears with
  no matching `DNS_RESPONSE_*` within a few seconds, the resolver
  itself is unreachable or dropping packets. Look for ICMP unreachable
  in the same direction.
- **REFUSED on a `.local` name** generally means the dnsmasq /
  resolver has `no-resolv` set with no `local=/local/` directive, so
  unknown `.local` names go through the "ask upstream → no upstream"
  path and dnsmasq returns REFUSED instead of NXDOMAIN.
- **SERVFAIL on a real name** is the most operationally serious
  outcome — the *resolver* believes the answer is unavailable. Check
  the resolver's upstream connectivity first.
