# 5GSM cause codes (TS 24.501 Annex A)

The 5G Session Management (5GSM) cause IE accompanies PDU SESSION
ESTABLISHMENT / MODIFICATION / RELEASE REJECT messages sent by the
SMF via the AMF towards the UE.

## Cause 8 — Operator determined barring

The subscription is barred from this service at the operator level.

## Cause 26 — Insufficient resources

SMF or UPF cannot admit the session right now (PDR/FAR/QER budget
exceeded, or UPF link saturated).

## Cause 27 — Missing or unknown DNN

The requested DNN is not known to SMF. Typical misconfig in
`smf.yaml`.

## Cause 28 — Unknown PDU session type

The UE asked for an IP type (IPv4 / IPv6 / IPv4v6 / Ethernet / unstructured)
the SMF does not support.

## Cause 29 — User authentication or authorization failed

Secondary authentication (DN-AAA) failed — usually a RADIUS/DIAMETER
back-end problem.

## Cause 31 — Request rejected, unspecified

Catch-all when nothing more specific applies.

## Cause 32 — Service option not supported

The requested capability is out of scope for the SMF.

## Cause 33 — Requested service option not subscribed

UDM/HSS says the subscriber is not entitled.

## Cause 36 — Regular deactivation

Not actually a failure — the network gracefully tore down the session
(e.g. on detach).

## Cause 38 — Network failure

SMF-internal or UPF-side failure surfaces as this cause.

## Cause 39 — Reactivation requested

Network wants the UE to re-establish the session; typical after idle
mode UPF migration.

## Cause 43 — Invalid PDU session identity

PDU session ID collides with an active one; usually an SMF<->UE state
drift.

## Cause 50 / 51 — IPv4 / IPv6 only allowed

The PDU session type requested is not permitted; the peer proposes a
narrower type.

## Cause 54 — PDU session does not exist

The UE asked to modify/release a session the SMF has no record of.
Typical after a restart.

## Cause 67 — Insufficient resources for specific slice and DNN

SM-layer admission control blocks the `(S-NSSAI, DNN)` tuple.

## Cause 69 — Insufficient resources for specific slice

S-NSSAI-wide SM admission control failure.

## Cause 70 — Missing or unknown DNN in a slice

The slice is valid but the DNN under it is not configured.

## Cause 72 — Max data rate per UE for UP integrity too low

UP integrity policy mandates a rate higher than the UE supports.

## Cause 83 — Semantically incorrect message

SMF cannot decode the PDU SESSION ESTABLISHMENT REQUEST IEs.

## Cause 95 — Protocol error, unspecified

Generic protocol error bucket.
