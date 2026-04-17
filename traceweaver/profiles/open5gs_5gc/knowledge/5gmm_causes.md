# 5GMM cause codes (TS 24.501 Annex A)

The 5G Mobility Management (5GMM) cause IE accompanies REGISTRATION
REJECT, AUTHENTICATION REJECT, SERVICE REJECT, and DEREGISTRATION
REQUEST messages sent by the AMF to the UE.

## Cause 3 — Illegal UE

The network has determined that the UE is illegal for the
registration area. The UE shall enter state 5GMM-DEREGISTERED and may
attempt registration again only after SIM/USIM replacement or
contacting the operator.

## Cause 5 — PEI not accepted

The requested PEI (IMEI/IMEISV) is not accepted by the network.
Usually indicates the device is blacklisted or not type-approved for
this PLMN.

## Cause 6 — Illegal ME

The ME (mobile equipment) has been blacklisted. Typically seen with
stolen devices.

## Cause 7 — 5GS services not allowed

The UE is subscribed for something other than 5GS (e.g. EPS-only
subscription).

## Cause 9 — UE identity cannot be derived by the network

The AMF cannot resolve the UE's SUCI/SUPI — typically an AUSF/UDM
lookup failure or a misconfigured SUPI in the HSS/UDM.

## Cause 10 — Implicitly de-registered

The AMF has locally cleared the UE's context. The UE must re-register.

## Cause 11 — PLMN not allowed

The UE's HPLMN does not match the serving PLMN's allowed list.

## Cause 12 — Tracking area not allowed

The UE is registered but this TA is forbidden for it. Re-selection to
a different cell may succeed.

## Cause 13 — Roaming not allowed in this tracking area

Roaming restrictions. The UE must exit the TA before retrying.

## Cause 15 — No suitable cells in tracking area

Radio-side reason: the UE has no acceptable cell.

## Cause 20 — MAC failure

The NAS integrity MAC check failed. Typical cause: AKA authentication
mismatch between UE and UDM/HSS (SQN out of sync, wrong K, or a race
after a K-update). This is THE most common "registration fails with
REJECT" story in Open5GS labs.

## Cause 21 — Synchronisation failure

AKA SQN (sequence number) is out of range. The UDM and USIM need to
resynchronize; the UE will typically send AUTHENTICATION FAILURE with
AUTS and the AMF will issue a fresh AUTHENTICATION REQUEST.

## Cause 22 — Congestion

The network (AMF/SMF) is overloaded or the DNN/S-NSSAI is at
admission-control limit. The UE should back off and retry.

## Cause 23 — UE security capabilities mismatch

The UE's NAS security capabilities the AMF saw do not match the
subscription — possible replay attempt, or a broken home network
routing.

## Cause 24 — Security mode rejected, unspecified

Generic bucket when the UE rejects SECURITY MODE COMMAND.

## Cause 27 / 73 — N1 mode not allowed

The UE is not entitled to N1 (5G NAS) mode in this PLMN.

## Cause 28 — Restricted service area

The UE is in a restricted service area for its subscription.

## Cause 43 — LADN not available

The Local Area Data Network targeted by the PDU session is out of
reach here.

## Cause 65 — Maximum number of PDU sessions reached

Per-subscription or per-NF limit hit.

## Cause 67 — Insufficient resources for specific slice and DNN

No admission headroom for `(S-NSSAI, DNN)`.

## Cause 69 — Insufficient resources for specific slice

Slice-wide admission failure.

## Cause 71 — ngKSI already in use

The AMF tried to reuse a key set identifier that is still allocated;
usually an AMF bug.

## Cause 72 — Non-5G authentication unacceptable

The UE reported a non-5G authentication that the AMF does not accept
(e.g. EAP-AKA' was required).

## Cause 75 — Serving network not authorized

AUSF could not authorize the serving network name.

## Cause 80 — Payload was not forwarded

AMF failed to route an NAS payload to the SMF (or vice versa) — check
SBI traces and SMF status.

## Cause 83 — Semantically incorrect message

The received NAS PDU is structurally unparseable. Usually indicates a
version mismatch or a wire-level corruption.

## Cause 91 — DNN not supported or not subscribed in the slice

The requested DNN is not available under `(S-NSSAI, UE subscription)`.
Typical misconfiguration: UDM has a different DNN set than SMF.
