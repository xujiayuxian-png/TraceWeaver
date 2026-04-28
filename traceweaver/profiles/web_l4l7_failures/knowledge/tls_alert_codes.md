# TLS Alert codes

RFC 5246 §7.2 (TLS 1.2) and RFC 8446 §6 (TLS 1.3).

## Important caveat: TLS 1.3 hides alerts

In **TLS 1.3** every post-handshake alert is encrypted inside an
`application_data` record (content type 23). Tshark CANNOT surface
`tls.alert_message.desc` for these, and **the wire pattern you see
when a TLS 1.3 handshake fails is just `Client Hello → Server Hello →
TCP RST`** — no plaintext alert at all.

Diagnose TLS 1.3 failures by **wire pattern**, not by alert code:

| pattern | likely cause |
| ------- | ------------ |
| RST immediately after Client Hello | TLS version mismatch / cipher unacceptable / SNI mapping failed at LB |
| RST after Server Hello but before any application_data | client rejected the certificate (expired / wrong CN / untrusted CA) |
| RST after a few application_data frames | application-layer error inside the encrypted channel; you can't tell from the pcap alone |

For **TLS 1.2** the alert is plaintext (`tls.alert_message.desc`):

| code | name                      | who sends it | typical cause |
| ---- | ------------------------- | ------------ | ------------- |
| 0    | close_notify              | either       | Graceful close, normal. |
| 10   | unexpected_message        | either       | Protocol violation. Usually middlebox interference. |
| 20   | bad_record_mac            | either       | Record MAC failed — encryption key mismatch or active tampering. |
| 22   | record_overflow           | either       | Record too large. |
| 30   | decompression_failure     | either       | Compression bug. Rare. |
| 40   | handshake_failure         | server       | No common cipher suite / protocol version with the client. |
| 41   | no_certificate (legacy)   | client       | TLS 1.0/1.1 only. Client refused to send a certificate. |
| 42   | bad_certificate           | client       | Cert is corrupt or has bad signature. |
| 43   | unsupported_certificate   | client       | Client doesn't support that cert type. |
| 44   | certificate_revoked       | client       | OCSP / CRL says revoked. |
| 45   | **certificate_expired**   | **client**   | **Server cert past `not_after` (or before `not_before`)**. The classic "I forgot to renew the cert" failure. |
| 46   | certificate_unknown       | client       | Some other cert problem the client can't classify. |
| 47   | illegal_parameter         | either       | Field in handshake had bogus value. |
| 48   | unknown_ca                | client       | Server cert not signed by a CA the client trusts. **Common with self-signed certs.** |
| 49   | access_denied             | server       | Server refuses to continue (e.g. client cert required but absent). |
| 50   | decode_error              | either       | Couldn't parse the record body. |
| 51   | decrypt_error             | either       | Signature didn't verify. |
| 70   | protocol_version          | either       | Client wanted TLS 1.0 but server requires 1.2+. |
| 71   | insufficient_security     | server       | Client offered only weak ciphers. |
| 80   | internal_error            | either       | Server crash / out of memory. |
| 86   | inappropriate_fallback    | server       | Client downgrade attempt detected (TLS_FALLBACK_SCSV). |
| 90   | user_canceled             | either       | User aborted (e.g. browser tab closed). |
| 100  | no_renegotiation          | either       | Server refuses renegotiation. |
| 109  | missing_extension         | server       | Required extension absent (TLS 1.3). |
| 110  | unsupported_extension     | either       | Extension provided that shouldn't be. |
| 112  | unrecognized_name         | server       | **SNI didn't match any virtual host.** Often surfaces as just "RST after Client Hello" instead of as a clean alert. |
| 113  | bad_certificate_status_response | client | OCSP stapling response was bad. |
| 116  | certificate_required      | server       | mTLS: client cert required but missing. |
| 120  | no_application_protocol   | server       | ALPN negotiation failed. |

## Diagnostic recipes

- **Cert expired** → On TLS 1.2, alert 45. On TLS 1.3, no alert visible
  — diagnose by "RST after Server Hello + no Finished record".
- **Self-signed cert / unknown CA** → On TLS 1.2, alert 48. Very
  common in dev environments where the client's CA bundle wasn't
  set up.
- **SNI mismatch** → On TLS 1.2, alert 112 OR alert 40. On TLS 1.3,
  often "RST after Client Hello" with no Server Hello at all.
- **No common cipher** → Alert 40 (handshake_failure). The client
  hello will list the cipher suites it offered; the absence of a
  server hello means none were acceptable.
