# Open5GS 5GC procedure cheat-sheets

Short summaries of the NAS/NGAP procedures whose names appear in the
`event` column. Use these to interpret "where did we stop?".

## Registration (initial)

1. UE -> AMF : REGISTRATION_REQUEST (over NGAP INITIAL_UE_MESSAGE)
2. AMF -> UE : AUTHENTICATION_REQUEST (AKA challenge, built from
   AUSF's response to `Nausf_UEAuthentication`).
3. UE -> AMF : AUTHENTICATION_RESPONSE.
   - If MAC / SQN checks fail the UE sends AUTHENTICATION_FAILURE
     instead; cause 20 (MAC_FAILURE) or 21 (SYNC_FAILURE).
4. AMF -> UE : SECURITY_MODE_COMMAND.
5. UE -> AMF : SECURITY_MODE_COMPLETE.
6. AMF -> UDM (via SBI) : Nudm_UECM_Registration /
   Nudm_SDM_Get (subscription data).
7. AMF -> UE : REGISTRATION_ACCEPT (5G-GUTI, allowed S-NSSAIs, TAI
   list).
8. UE -> AMF : REGISTRATION_COMPLETE.

If any step above errors, the AMF sends REGISTRATION_REJECT with a
5GMM cause. The cause usually names the responsible party (UDM, AUSF,
config).

## PDU Session Establishment

1. UE -> AMF : UL NAS TRANSPORT carrying PDU SESSION ESTABLISHMENT
   REQUEST for a given DNN + S-NSSAI.
2. AMF -> SMF : Nsmf_PDUSession_CreateSMContext (SBI).
3. SMF -> UPF : PFCP SESSION_ESTABLISHMENT_REQUEST.
4. UPF -> SMF : PFCP SESSION_ESTABLISHMENT_RESPONSE (cause = Request
   accepted).
5. SMF -> AMF : Namf_Communication_N1N2MessageTransfer containing
   PDU SESSION ESTABLISHMENT ACCEPT NAS PDU.
6. AMF -> UE : DL NAS TRANSPORT + NGAP PDU_SESSION_RESOURCE_SETUP.
7. UE <-> UPF : user-plane traffic via N3.

If step 2, 3 or 5 errors, SMF sends PDU_SESSION_ESTABLISHMENT_REJECT
with a 5GSM cause.

## UE-initiated de-registration

1. UE -> AMF : DEREGISTRATION_REQUEST_UE_ORIG.
2. AMF -> SMF : Nsmf_PDUSession_ReleaseSMContext for each active
   session.
3. SMF -> UPF : PFCP SESSION_DELETION_REQUEST / RESPONSE.
4. AMF -> UE : DEREGISTRATION_ACCEPT_UE_ORIG.

Regular deactivation is signaled with 5GSM cause 36 and is not an
error.

## Periodic / mobility registration

A REGISTRATION_REQUEST with the "registration type" IE set to
periodic / mobility is a lighter-weight variant — if authentication
context is still valid, AMF may skip the AKA handshake and go
directly to REGISTRATION_ACCEPT.

## SBI service patterns (what paths look like)

- `POST /namf-comm/v1/ue-contexts/{ueCtxId}/n1-n2-messages`
  — AMF to SMF or SMF to AMF, N1/N2 bridging.
- `GET /nudm-sdm/v2/{supi}/am-data`
  — AMF fetching access-and-mobility subscription data from UDM.
- `POST /nausf-auth/v1/ue-authentications`
  — AMF starting UE authentication at AUSF.
- `POST /nsmf-pdusession/v1/sm-contexts`
  — AMF creating SM context for a PDU session.

A 4xx status from any of these points to a concrete failure the LLM
can quote in its diagnosis.

## PFCP heartbeat

HEARTBEAT_REQUEST/RESPONSE between SMF and UPF is continuous. Absence
of responses is itself diagnostic (UPF is unreachable). Reach for
HEARTBEAT only when investigating UPF-side outages.
