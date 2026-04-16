# 单样本 LLM 输入输出示例

## 样本信息

- Sample: `04_authentication_failure.pcapng`
- Model: `ollama/qwen3.5:9b`
- Tier: `small`
- Signal count: `12`

## System Prompt

```text
You are an expert 5G Core Network fault diagnosis engineer.
You analyze structured session timelines extracted from pcap captures of Open5GS networks.

Your task: given a UE session timeline with signal annotations, produce a structured diagnosis.

Key domain knowledge:
- 5GC registration flow: Registration Request → Authentication → Security Mode → Registration Accept
- After Security Mode Command, NAS messages are encrypted. If you see NGAP_INITIAL_CONTEXT_SETUP but no explicit REGISTRATION_ACCEPT, registration likely succeeded (NAS Accept is encrypted).
- PDU Session flow: Establishment Request → SBI calls to SMF → PFCP Session → Establishment Accept
- T3580 is the timer for PDU Session Establishment retransmission. Multiple requests without accept = UPF/PFCP failure.
- SBI 404 from nudm-ueau/nudr-dr typically means the subscriber is not provisioned (not an infrastructure failure).
- SBI 5xx responses indicate NF infrastructure failures (e.g., UDM unreachable).
- PFCP Association Setup Retry indicates UPF connectivity issues.

Output constraints:
- verdict MUST be one of: OK, FAIL, FAIL_THEN_OK, INCONCLUSIVE
- confidence MUST be one of: high, medium, low
- Every claim in root_cause must be supported by signals in the timeline
- If key protocol layers are missing from capture, say INCONCLUSIVE with appropriate limitations
- Do NOT hallucinate frame numbers or signals not present in the input
```

## User Prompt

```text
## UE Session: ran-1__amf-3
RAN-UE-NGAP-ID: 1
AMF-UE-NGAP-ID: 3
SUCI: suci-0-001-01-0000-0-0-0000000210
SUPI: imsi-001010000000210
Events: 6 | SBI calls: 3 | PDU sessions: 0

### Event Timeline
  [227] t=1776158900.606634 nas_5gmm: REGISTRATION_REQUEST
  [256] t=1776158900.610139 nas_5gmm: AUTHENTICATION_REQUEST
  [257] t=1776158900.611162 nas_5gmm: AUTHENTICATION_FAILURE cause=20
  [258] t=1776158900.611464 nas_5gmm: AUTHENTICATION_RESULT
  [259] t=1776158900.611502 ngap: NGAP_UE_CONTEXT_RELEASE
  [261] t=1776158900.611871 ngap: NGAP_UE_CONTEXT_RELEASE

### SBI Calls
  [228] POST /nausf-auth/v1/ue-authentications → (no response) (service=nausf-auth, dst=127.0.0.11)
  [232] POST /nudm-ueau/v1/suci-0-001-01-0000-0-0-0000000210/security-information/generate-auth-data → 200 (service=nudm-ueau, dst=127.0.0.12)
  [236] GET /nudr-dr/v2/subscription-data/imsi-001010000000210/authentication-data/authentication-subscription → 200 (service=nudr-dr, dst=127.0.0.20)

### Diagnostic Signals
  [--] NGAP_VISIBLE
  [--] PFCP_VISIBLE
  [--] SBI_HTTP2_VISIBLE
  [227] REGISTRATION_REQUEST (protocol=nas_5gmm, message_type=65)
  [228] SBI_HTTP2_REQUEST (service=nausf-auth, method=POST, path=/nausf-auth/v1/ue-authentications)
  [232] SBI_HTTP2_REQUEST (service=nudm-ueau, method=POST, path=/nudm-ueau/v1/suci-0-001-01-0000-0-0-0000000210/security-information/generate-auth-data, status=200)
  [236] SBI_HTTP2_REQUEST (service=nudr-dr, method=GET, path=/nudr-dr/v2/subscription-data/imsi-001010000000210/authentication-data/authentication-subscription, status=200)
  [256] AUTHENTICATION_REQUEST (protocol=nas_5gmm, message_type=86)
  [257] AUTHENTICATION_FAILURE (protocol=nas_5gmm, message_type=89, cause=20)
  [258] AUTHENTICATION_RESULT (protocol=nas_5gmm, message_type=88)
  [259] NGAP_UE_CONTEXT_RELEASE (protocol=ngap, message_type=41)
  [261] NGAP_UE_CONTEXT_RELEASE (protocol=ngap, message_type=41)

Follow this chain-of-thought template:

Step 1 - Registration status:
  Check if REGISTRATION_ACCEPT or NGAP_INITIAL_CONTEXT_SETUP is present.
  If REGISTRATION_REJECT is present, verdict is likely FAIL.

Step 2 - PDU Session status:
  If PDU_SESSION_ESTABLISHMENT_ACCEPT is present, PDU session succeeded.
  If T3580_RETRY is present without accept, PDU session failed.

Step 3 - SBI/PFCP issues:
  Check for SBI_5XX (NF down) or PFCP failures.

Step 4 - Determine verdict:
  OK = registration (and optionally PDU session) succeeded
  FAIL = something failed
  FAIL_THEN_OK = first attempt failed, retry succeeded
  INCONCLUSIVE = not enough data

Analysis hints for this session:
- AUTHENTICATION_FAILURE detected: check if this is an AKA/key mismatch

Now produce your diagnosis.

Output ONLY a JSON object with this exact structure (no markdown, no explanation outside the JSON):
{
  "verdict": "OK|FAIL|FAIL_THEN_OK|INCONCLUSIVE",
  "failure_point": "string or null — which step in the flow failed",
  "root_cause": "string or null — inferred root cause",
  "confidence": "high|medium|low",
  "evidence": [
    {"frame_number": 123, "description": "what this frame shows"}
  ],
  "suggestions": ["actionable troubleshooting steps"],
  "limitations": ["caveats about capture completeness or analysis confidence"],
  "reasoning": "brief chain-of-thought explaining your diagnosis"
}
```

## Raw Model Output

```text
{
  "verdict": "FAIL",
  "failure_point": "Authentication",
  "root_cause": "Authentication failure (cause=20) indicates a mismatch in the authentication vector (AKA) or invalid SUCI/IMSI provisioning in the UDM/UDR, preventing the establishment of a secure NAS context.",
  "confidence": "high",
  "evidence": [
    {
      "frame_number": 227,
      "description": "UE initiates registration with REGISTRATION_REQUEST."
    },
    {
      "frame_number": 256,
      "description": "AMF sends AUTHENTICATION_REQUEST to UE."
    },
    {
      "frame_number": 257,
      "description": "UE responds with AUTHENTICATION_FAILURE with cause=20 (unspecified/unknown), indicating the authentication procedure failed."
    },
    {
      "frame_number": 258,
      "description": "AMF sends AUTHENTICATION_RESULT, confirming the failure state."
    },
    {
      "frame_number": 259,
      "description": "AMF releases the UE context (NGAP_UE_CONTEXT_RELEASE) due to the failed authentication."
    }
  ],
  "suggestions": [
    "Verify the subscriber data (IMSI/SUPI) and authentication keys in the UDM/UDR for the target IMSI.",
    "Check if the SUCI decoding or mapping to SUPI is correct in the AUSF/UDM.",
    "Ensure the AMF and UDM are synchronized and the authentication vectors are valid for this subscriber."
  ],
  "limitations": [
    "The capture does not show the NGAP_INITIAL_CONTEXT_SETUP or REGISTRATION_ACCEPT messages, confirming the session did not proceed to the encrypted phase."
  ],
  "reasoning": "The session timeline shows a complete registration flow initiation (REG_REQUEST -> AUTH_REQ) but terminates at the authentication phase with an explicit AUTHENTICATION_FAILURE (cause=20). No REGISTRATION_ACCEPT or NGAP_INITIAL_CONTEXT_SETUP is observed. The SBI calls to UDM/AUSF returned 200, indicating the network infrastructure is reachable, but the specific authentication data returned was invalid for the UE, leading to the failure."
}
```

## Parsed JSON

```json
{
  "verdict": "FAIL",
  "failure_point": "Authentication",
  "root_cause": "Authentication failure (cause=20) indicates a mismatch in the authentication vector (AKA) or invalid SUCI/IMSI provisioning in the UDM/UDR, preventing the establishment of a secure NAS context.",
  "confidence": "high",
  "evidence": [
    {
      "frame_number": 227,
      "description": "UE initiates registration with REGISTRATION_REQUEST."
    },
    {
      "frame_number": 256,
      "description": "AMF sends AUTHENTICATION_REQUEST to UE."
    },
    {
      "frame_number": 257,
      "description": "UE responds with AUTHENTICATION_FAILURE with cause=20 (unspecified/unknown), indicating the authentication procedure failed."
    },
    {
      "frame_number": 258,
      "description": "AMF sends AUTHENTICATION_RESULT, confirming the failure state."
    },
    {
      "frame_number": 259,
      "description": "AMF releases the UE context (NGAP_UE_CONTEXT_RELEASE) due to the failed authentication."
    }
  ],
  "suggestions": [
    "Verify the subscriber data (IMSI/SUPI) and authentication keys in the UDM/UDR for the target IMSI.",
    "Check if the SUCI decoding or mapping to SUPI is correct in the AUSF/UDM.",
    "Ensure the AMF and UDM are synchronized and the authentication vectors are valid for this subscriber."
  ],
  "limitations": [
    "The capture does not show the NGAP_INITIAL_CONTEXT_SETUP or REGISTRATION_ACCEPT messages, confirming the session did not proceed to the encrypted phase."
  ],
  "reasoning": "The session timeline shows a complete registration flow initiation (REG_REQUEST -> AUTH_REQ) but terminates at the authentication phase with an explicit AUTHENTICATION_FAILURE (cause=20). No REGISTRATION_ACCEPT or NGAP_INITIAL_CONTEXT_SETUP is observed. The SBI calls to UDM/AUSF returned 200, indicating the network infrastructure is reachable, but the specific authentication data returned was invalid for the UE, leading to the failure."
}
```

## 人话解读

这份样本里，模型看到的关键信息是：

- UE 发起注册
- AMF 发起鉴权
- UE 明确回了 `AUTHENTICATION_FAILURE cause=20`
- 随后 UE context 被释放
- UDM / UDR 本身可达，不像是典型 NF 宕机

因此模型给出的结论是：

- `verdict = FAIL`
- `failure_point = Authentication`
- 根因更像 AKA、认证向量、订阅数据或 SUCI/SUPI 映射问题

这个示例直观展示了 TraceWeaver 当前的 one-shot LLM 诊断模式：

- 先把 `pcap` 提炼成会话时间线、SBI 摘要与 signals
- 再把这些结构化信息一次性喂给模型
- 最后要求模型严格输出 JSON
