# 5GC 跨协议关联详细方案

## 1. 问题本质

5GC 一个 UE 的注册或 PDU Session 建立涉及 4 种协议：

- **NGAP**：gNB ↔ AMF（承载 NAS）
- **NAS-5GS**：UE ↔ AMF（封装在 NGAP 中）
- **HTTP2 SBI**：AMF ↔ AUSF/UDM/PCF/SMF（核心网内部）
- **PFCP**：SMF ↔ UPF（用户面控制）

抓包中看到的是离散的帧，需要把它们关联成一个完整的 UE 会话。

难度在于：**这四种协议之间没有统一的全局 Session ID**，需要通过多种关联键 + 启发式推断来建立关系。

---

## 2. 关联键总览

```text
UE 视角          NGAP/NAS 域           SBI 域              PFCP 域
─────────────────────────────────────────────────────────────────────
                 RAN-UE-NGAP-ID ──┐
                 AMF-UE-NGAP-ID ──┼── UE 级关联
                 SUCI/SUPI ───────┼──→ SBI URL 中的 SUPI ──┐
                                  │                        │
                 PDU Session ID ──┼──→ SBI path 中的       │
                 (NAS 层)         │   pdu-session-id ──────┼── Session 级关联
                                  │                        │
                                  │   SMF IP ──────────────┼──→ PFCP src IP
                                  │   SBI context-id ──────┘   SEID
```

### 2.1 确定性关联键（直接匹配）

| 关联键 | 协议域 | 可靠性 | 说明 |
|--------|--------|--------|------|
| RAN-UE-NGAP-ID + AMF-UE-NGAP-ID | NGAP ↔ NAS | 高 | 同一帧中同时存在 |
| SUPI (URL path) | NAS ↔ SBI | 高 | nudm-uecm/nudm-sdm/nudm-ueau/namf-comm 的 URL path 中包含 SUPI |
| SUCI (URL path) | NAS ↔ SBI | 高 | nudm-ueau 初始认证请求的 URL path 中包含 SUCI |
| HTTP2 stream ID | SBI 内部 | 高 | 同一 HTTP2 stream 的 request/response |

### 2.1a Open5GS SBI URL 中 SUPI 覆盖率（基于源码分析）

> 以下结论基于 Open5GS 源码实际分析，已验证。

| SBI 服务 | URL 路径模式 | SUPI 在 URL？ | SUPI 位置 |
|-----------|----------------|:---:|-----------|
| nudm-uecm | `/nudm-uecm/v1/{supi}/registrations/...` | ✅ | URL path[0] |
| nudm-sdm | `/nudm-sdm/v2/{supi}/am-data` 等 | ✅ | URL path[0] |
| nudm-ueau | `/nudm-ueau/v1/{suci}/security-information/...` | ✅ | URL path[0]（SUCI） |
| nudm-ueau | `/nudm-ueau/v1/{supi}/auth-events` | ✅ | URL path[0] |
| namf-comm | `/namf-comm/v1/ue-contexts/{supi}/n1-n2-messages` | ✅ | URL path[1] |
| **nausf-auth** | `/nausf-auth/v1/ue-authentications` | ❌ | **body 中** (`supi_or_suci`) |
| **nsmf-pdusession** | `/nsmf-pdusession/v1/sm-contexts` | ❌ | **body 中** (`SmContextCreateData.supi`) |
| **nsmf-pdusession** (update) | `{sm_context_resource_uri}/modify` | ❌ | resource_uri 是数字索引 |
| **npcf-am-policy** | `/npcf-am-policy-control/v1/policies` | ❌ | **body 中** |
| **npcf-smpolicy** | `/npcf-smpolicycontrol/v1/sm-policies` | ❌ | **body 中** |

**关键发现**：
- UDM 相关调用（nudm-*）：SUPI/SUCI **始终在 URL path 中**，是最可靠的关联源
- AMF→SMF、AMF→PCF、SMF→PCF、AMF→AUSF：SUPI 在 **HTTP body 中**，无法通过 URL 提取
- AUSF 的 `ctx_id` 是数字池索引（如 `1`, `2`），**不含 SUCI**
- SMF 的 `sm_context_ref` 也是数字索引

**关联策略影响**：
1. 优先用 nudm-* 调用的 URL path 提取 SUPI，作为 SBI → UE Session 的主关联路径
2. 对于 nausf-auth、nsmf-pdusession、npcf-* 等无 URL SUPI 的调用，采用 **IP + 时间窗口** 启发式关联
3. 可选增强：用 tshark `-T json` 解析 HTTP2 body，从 JSON 中提取 SUPI（作为 P2 增强功能）

### 2.2 启发式关联键（需要推断）

| 关联键 | 协议域 | 可靠性 | 说明 |
|--------|--------|--------|------|
| SMF IP + 时间窗口 | SBI ↔ PFCP | 中-高 | SMF 的 SBI IP 与 PFCP 源 IP 相同 |
| AMF IP + 时间窗口 | NAS ↔ SBI | 中 | NAS 事件后短时间内 AMF 发出的 SBI 请求 |
| NF IP + 时间窗口 | SBI(nudm) ↔ SBI(nausf/nsmf/npcf) | 中 | nudm 已关联 SUPI 的 NF IP → 同 IP 的其他 SBI 调用 |
| SEID | PFCP 内部 | 高 | PFCP 请求/响应匹配 |
| PDU Session ID | NAS ↔ SBI body | 中 | nsmf-pdusession body 中的 pdu_session_id（需 JSON 解析） |

---

## 3. 一次 tshark 提取所有关联所需字段

用一次 tshark 调用提取所有目标协议帧的关键字段：

```bash
tshark -r file.pcap \
  -Y "ngap || nas-5gs || http2 || pfcp" \
  -T fields \
  -E separator='\t' \
  -E occurrence=a \
  -E aggregator='|' \
  -E header=y \
  -e frame.number \
  -e frame.time_epoch \
  -e frame.time_relative \
  -e frame.protocols \
  -e ip.src \
  -e ip.dst \
  -e frame.info \
  -e tcp.stream \
  -e ngap.procedureCode \
  -e ngap.RAN_UE_NGAP_ID \
  -e ngap.AMF_UE_NGAP_ID \
  -e ngap.pDUSessionID \
  -e nas_5gs.mm.message_type \
  -e nas_5gs.mm.5gmm_cause \
  -e nas_5gs.sm.message_type \
  -e nas_5gs.sm.5gsm_cause \
  -e nas_5gs.mm.suci.scheme_output \
  -e nas_5gs.mm.type_of_identity \
  -e nas_5gs.pdu_session_id \
  -e http2.headers.method \
  -e http2.headers.path \
  -e http2.headers.status \
  -e http2.streamid \
  -e pfcp.msg_type \
  -e pfcp.seid \
  -e pfcp.f_seid.ipv4 \
  -e pfcp.cause \
  -e http2.headers.host \
  -e http2.headers.scheme \
  -e http2.headers.authority
```

**注意**：这是一次性提取。后续关联默认在 Python 内存中完成，不再调用 tshark。
对于超出实验室规模的大抓包，应允许落盘到中间格式（如 `jsonl` / `sqlite`）后再做关联。

---

## 4. 分步关联算法

### 4.1 第一步：NGAP/NAS 分组（UE 级）

**输入**：所有含 NGAP/NAS 字段的帧

**算法**：

```python
def group_ue_sessions(records: list[NormalizedRecord]) -> dict[str, UESession]:
    """按 (RAN-UE-NGAP-ID, AMF-UE-NGAP-ID) 分组"""
    sessions = {}

    for record in records:
        if record.primary_protocol not in ("ngap", "nas_5gs"):
            continue

        ran_id = record.fields.get("ngap.RAN_UE_NGAP_ID")
        amf_id = record.fields.get("ngap.AMF_UE_NGAP_ID")

        if not ran_id and not amf_id:
            continue

        # NGAP 初始消息可能只有 RAN-UE-NGAP-ID，
        # 后续消息同时有两个 ID。
        # 处理策略：
        # 1. 先用 RAN-UE-NGAP-ID 创建临时 session
        # 2. 当 AMF-UE-NGAP-ID 出现时，合并为正式 session key
        key = _resolve_ue_key(ran_id, amf_id, sessions)

        if key not in sessions:
            sessions[key] = UESession(session_id=key)

        session = sessions[key]
        event = identify_event(record)  # 见 4.2
        session.registration_timeline.events.append(event)

        # 提取 SUCI/SUPI（如果存在）
        suci = record.fields.get("nas_5gs.mm.suci.scheme_output")
        if suci:
            session.suci = suci

    return sessions
```

**关键细节**：

- `InitialUEMessage`（NGAP procedureCode=15）只有 `RAN-UE-NGAP-ID`
- `DownlinkNASTransport`（procedureCode=4）同时携带 `RAN-UE-NGAP-ID` 和 `AMF-UE-NGAP-ID`
- 第一个包含 `AMF-UE-NGAP-ID` 的帧确定了完整的 UE session key
- 需要处理 key 合并：从 `(ran_id, None)` 到 `(ran_id, amf_id)` 的过渡

### 4.2 第二步：NAS 事件识别

**输入**：单条 NormalizedRecord

**算法**：基于 `nas_5gs.mm.message_type` 或 `nas_5gs.sm.message_type` 做确定性映射

```python
NAS_MM_EVENT_MAP = {
    65: "REGISTRATION_REQUEST",
    66: "REGISTRATION_ACCEPT",
    67: "REGISTRATION_COMPLETE",
    68: "REGISTRATION_REJECT",
    69: "DEREGISTRATION_REQUEST_UE_ORIG",
    70: "DEREGISTRATION_ACCEPT_UE_ORIG",
    71: "DEREGISTRATION_REQUEST_UE_TERM",
    72: "DEREGISTRATION_ACCEPT_UE_TERM",
    76: "SERVICE_REJECT",
    86: "AUTHENTICATION_REQUEST",
    87: "AUTHENTICATION_RESPONSE",
    88: "AUTHENTICATION_RESULT",
    89: "AUTHENTICATION_FAILURE",
    90: "AUTHENTICATION_REJECT",
    93: "SECURITY_MODE_COMMAND",
    94: "SECURITY_MODE_COMPLETE",
    95: "SECURITY_MODE_REJECT",
    100: "5GMM_STATUS",
}

NAS_SM_EVENT_MAP = {
    193: "PDU_SESSION_ESTABLISHMENT_REQUEST",
    194: "PDU_SESSION_ESTABLISHMENT_ACCEPT",
    195: "PDU_SESSION_ESTABLISHMENT_REJECT",
    196: "PDU_SESSION_AUTHENTICATION_COMMAND",
    201: "PDU_SESSION_MODIFICATION_REQUEST",
    202: "PDU_SESSION_MODIFICATION_ACCEPT",
    203: "PDU_SESSION_MODIFICATION_REJECT",
    209: "PDU_SESSION_RELEASE_REQUEST",
    210: "PDU_SESSION_RELEASE_REJECT",
    211: "PDU_SESSION_RELEASE_COMMAND",
    212: "PDU_SESSION_RELEASE_COMPLETE",
    214: "5GSM_STATUS",
}
```

### 4.3 第三步：HTTP2 SBI 关联到 UE Session

**输入**：所有 HTTP2 帧 + 已分组的 UE Sessions

**算法**：

```python
def correlate_sbi_to_ue(
    http2_records: list[NormalizedRecord],
    ue_sessions: dict[str, UESession],
) -> None:
    """将 SBI 调用关联到对应的 UE Session"""

    # 构建 SUCI/SUPI → UE Session 的反向索引
    identity_index: dict[str, UESession] = {}
    for session in ue_sessions.values():
        if session.suci:
            identity_index[session.suci] = session
        if session.supi:
            identity_index[session.supi] = session

    for record in http2_records:
        path = record.fields.get("http2.headers.path", "")
        method = record.fields.get("http2.headers.method", "")
        status = record.fields.get("http2.headers.status")
        stream_id = record.fields.get("http2.streamid")
        connection_key = record.connection_key

        if not path:
            continue

        # 策略 1：从 URL path 中提取 SUPI/SUCI
        # 注意：只有 nudm-*/namf-comm 的 URL 中包含 SUPI
        # nausf-auth/nsmf-pdusession/npcf-* 的 URL 中不包含 SUPI
        identity = extract_identity_from_path(path)
        if identity and identity in identity_index:
            session = identity_index[identity]
            sbi_call = SBICall(
                connection_key=connection_key,
                stream_id=int(stream_id) if stream_id else 0,
                method=method,
                path=path,
                status=int(status) if status else None,
                request_frame=record.frame_number if method else 0,
                response_frame=record.frame_number if status else 0,
                service=extract_sbi_service(path),
                src_ip=record.src_ip,
                dst_ip=record.dst_ip,
                timestamp=record.timestamp,
            )
            session.sbi_calls.append(sbi_call)
            continue

        # 策略 2：基于已关联 NF IP + 时间窗口的启发式关联
        # 适用于 nausf-auth/nsmf-pdusession/npcf-* 等 URL 无 SUPI 的调用
        # 思路：如果 AMF IP X 已通过 nudm 调用关联到 UE Session A，
        #       则同一 AMF IP X 发出的时间窗口内的 nausf/nsmf/npcf 调用也属于 A
        candidates = match_by_nf_ip_and_time(record, ue_sessions, window_ms=2000)
        if len(candidates) == 1:
            candidates[0].sbi_calls.append(build_sbi_call(record))
        elif len(candidates) > 1:
            emit_ambiguous_link(record, candidates)


def extract_identity_from_path(path: str) -> Optional[str]:
    """从 SBI URL path 中提取 SUPI/SUCI/IMSI

    基于 Open5GS 源码分析，URL path 中包含 SUPI/SUCI 的服务：
    - /nudm-uecm/v1/imsi-460010000000001/registrations/amf-3gpp-access  ✅ SUPI
    - /nudm-sdm/v2/imsi-460010000000001/am-data                        ✅ SUPI
    - /nudm-ueau/v1/suci-0-...-f.../security-information/...           ✅ SUCI
    - /nudm-ueau/v1/imsi-460010000000001/auth-events                   ✅ SUPI
    - /namf-comm/v1/ue-contexts/imsi-460010000000001/n1-n2-messages     ✅ SUPI

    URL path 中 **不包含** SUPI/SUCI 的服务（需要 IP+时间窗口关联）：
    - /nausf-auth/v1/ue-authentications         (SUCI 在 body 中)
    - /nsmf-pdusession/v1/sm-contexts           (SUPI 在 body 中)
    - /npcf-am-policy-control/v1/policies       (SUPI 在 body 中)
    - /npcf-smpolicycontrol/v1/sm-policies      (SUPI 在 body 中)
    """
    # 匹配 SUCI 格式: suci-0-...-...-...
    suci_match = re.search(r'(suci-0-[\w-]+)', path)
    if suci_match:
        return suci_match.group(1)

    # 匹配 IMSI/SUPI 格式: imsi-460010000000001
    imsi_match = re.search(r'(imsi-\d+)', path)
    if imsi_match:
        return imsi_match.group(1)

    return None


def extract_sbi_service(path: str) -> str:
    """从 SBI URL 提取服务名

    例如 /nausf-auth/v1/... → nausf-auth
    """
    match = re.match(r'/([^/]+)/', path)
    return match.group(1) if match else "unknown"
```

**SBI 请求/响应配对**：

同一个 HTTP2 stream ID 只在单个连接内唯一。
配对时必须先按 `connection_key + stream_id` 分组，再配对 request（有 method）和 response（有 status）。

```python
def pair_sbi_requests(sbi_calls: list[SBICall]) -> list[SBICall]:
    """将同一 stream ID 的 request 和 response 合并"""
    by_stream: dict[tuple[str, int], list[SBICall]] = {}
    for call in sbi_calls:
        key = (call.connection_key, call.stream_id)
        by_stream.setdefault(key, []).append(call)

    paired = []
    for (connection_key, stream_id), calls in by_stream.items():
        merged = SBICall(connection_key=connection_key, stream_id=stream_id, ...)
        for c in calls:
            if c.method:
                merged.method = c.method
                merged.path = c.path
                merged.request_frame = c.request_frame
            if c.status is not None:
                merged.status = c.status
                merged.response_frame = c.response_frame
        paired.append(merged)
    return paired
```

### 4.4 第四步：PDU Session 关联

**输入**：UE Session 的事件 + SBI 调用

```python
def build_pdu_sessions(session: UESession) -> list[PDUSessionFlow]:
    """从 UE Session 中提取 PDU Session 流程"""
    pdu_sessions = {}

    # 从 NAS 事件中提取 PDU Session
    for event in session.registration_timeline.events:
        pdu_id = event.key_fields.get("nas_5gs.pdu_session_id")
        if pdu_id and event.event_type.startswith("PDU_SESSION_"):
            if pdu_id not in pdu_sessions:
                pdu_sessions[pdu_id] = PDUSessionFlow(pdu_session_id=pdu_id)
            pdu_sessions[pdu_id].timeline.events.append(event)

    # 将 SBI 调用关联到 PDU Session
    for sbi_call in session.sbi_calls:
        if "nsmf-pdusession" in sbi_call.service:
            # SMF 相关 SBI 调用属于 PDU Session 流程
            # 通过时间窗口匹配到最近的 PDU Session
            pdu = match_sbi_to_pdu_session(sbi_call, pdu_sessions)
            if pdu:
                pdu.sbi_calls.append(sbi_call)

    return list(pdu_sessions.values())
```

### 4.5 第五步：PFCP 关联到 PDU Session

**输入**：PFCP 帧 + 已组装的 PDU Sessions

**策略**：SMF 的 IP 地址是关键桥梁。

```python
def correlate_pfcp_to_pdu(
    pfcp_records: list[NormalizedRecord],
    pdu_sessions: list[PDUSessionFlow],
    smf_ips: set[str],  # 从 SBI 调用中推断出的 SMF IP
) -> None:
    """
    关联策略：
    1. PFCP 帧的 src IP 应该是 SMF IP
    2. 时间窗口：PFCP 在 SBI nsmf-pdusession 调用之后短时间内出现
    3. 如果抓包中只有一个 PDU Session 流程，直接关联
    """
    for record in pfcp_records:
        src_ip = record.src_ip

        # 确认是 SMF 发出的 PFCP
        if src_ip not in smf_ips:
            # 可能是 UPF 的响应，检查 dst_ip
            if record.dst_ip not in smf_ips:
                continue

        pfcp_flow = PFCPFlow(
            seid=record.fields.get("pfcp.seid"),
            msg_type=record.fields.get("pfcp.msg_type"),
            cause=record.fields.get("pfcp.cause"),
            frame_number=record.frame_number,
            timestamp=record.timestamp,
        )

        # 找到时间最近的 PDU Session
        best_pdu = find_nearest_pdu_session(
            pfcp_flow.timestamp,
            pdu_sessions,
            max_window_ms=5000,
        )
        if best_pdu:
            best_pdu.pfcp_flows.append(pfcp_flow)
```

---

## 5. SMF IP 地址推断

PFCP 关联的关键前提是知道 SMF 的 IP。推断方法：

```python
def infer_smf_ips(ue_sessions: dict[str, UESession]) -> set[str]:
    """从 SBI 调用中推断 SMF IP

    AMF 调用 SMF 的 SBI 接口（nsmf-pdusession）：
    - HTTP2 请求的 dst IP 就是 SMF IP
    """
    smf_ips = set()
    for session in ue_sessions.values():
        for sbi_call in session.sbi_calls:
            if "nsmf" in sbi_call.service:
                # 这条 SBI 调用的目标就是 SMF
                smf_ips.add(sbi_call.dst_ip)
    return smf_ips
```

类似地可以推断 AMF/AUSF/UDM/PCF 的 IP：

```python
SBI_SERVICE_TO_NF = {
    "nausf-auth": "AUSF",
    "nudm-uecm": "UDM",
    "nudm-sdm": "UDM",
    "npcf-am-policy-control": "PCF",
    "npcf-smpolicycontrol": "PCF",
    "nsmf-pdusession": "SMF",
    "namf-comm": "AMF",
}
```

---

## 6. 完整关联流程图

```text
Phase 1: 一次 tshark 提取
    │
    ▼
Phase 2: NGAP/NAS 分组
    按 (RAN-UE-NGAP-ID, AMF-UE-NGAP-ID) 分组
    提取 SUCI/SUPI
    识别 NAS 事件
    │
    ▼
Phase 3: HTTP2 SBI 关联
    3a. URL path 中提取 SUPI/SUCI → 匹配 UE Session
    3b. stream ID 配对 request/response
    3c. IP+时间窗口兜底
    推断各 NF IP 地址
    │
    ▼
Phase 4: PDU Session 组装
    从 NAS PDU Session 事件按 PDU Session ID 分组
    将 nsmf SBI 调用按时间窗口匹配到 PDU Session
    │
    ▼
Phase 5: PFCP 关联
    用推断出的 SMF IP 识别 PFCP 帧
    按时间窗口匹配到 PDU Session
    │
    ▼
输出: UESession{ timeline, sbi_calls, pdu_sessions[{ timeline, sbi_calls, pfcp_flows }] }
```

---

## 7. 边界情况与降级策略

### 7.1 SUCI/SUPI 提取失败

**场景**：加密 SUCI、或 tshark 版本未解码

**降级**：仅靠 NGAP ID 做 UE 级分组，SBI 调用通过 IP + 时间窗口关联

### 7.2 多 UE 共存

**场景**：抓包中有多个 UE 同时操作

**处理**：每个 (RAN-UE-NGAP-ID, AMF-UE-NGAP-ID) 对产生独立的 UE Session。SBI 关联通过 SUPI 区分。

### 7.3 SBI URL 中无身份标识

**场景**：某些 PCF 调用的 URL 中不含 SUPI

**降级**：IP + 时间窗口关联。如果窗口内有多个候选 UE Session，标记为 `ambiguous`，而不是伪装成单一 `low_confidence` 结果。

### 7.4 抓包不完整

**场景**：只抓到了 N2 接口或只抓到了 SBI 接口

**处理**：只组装能看到的部分。缺失部分标记为 `not_captured`，而不是报错。这个信息本身就是有价值的诊断线索。

### 7.5 NGAP ID 复用

**场景**：RAN-UE-NGAP-ID 可能在 UE 断开后被复用

**处理**：加入时间间隔检测。如果同一 RAN-UE-NGAP-ID 的帧间隔超过阈值（如 30s），视为不同 UE Session。

---

## 8. 关联置信度标记

每个关联关系附带置信度：

```python
class CorrelationLink(BaseModel):
    source_frame: int
    target_frame: int
    correlation_type: str      # "ngap_id", "supi_url_match", "nf_ip_time_window"
    confidence: str            # "high", "medium", "low"
    status: str = "resolved"  # "resolved", "ambiguous", "unresolved"

# 置信度规则：
# - NGAP ID 匹配 → high
# - SUPI/SUCI URL path 匹配（nudm-*/namf-comm） → high
# - 已关联 NF IP + 时间窗口 (< 500ms)（nausf/nsmf/npcf） → medium
# - 已关联 NF IP + 时间窗口 (500ms - 5s) → low
# - 仅时间窗口（无 IP 匹配）→ very_low
```

---

## 9. 实现优先级

1. **P0**：NGAP/NAS 分组（最确定，最有价值）
2. **P0**：NAS 事件识别
3. **P0**：SBI URL SUPI/SUCI 匹配（nudm-*/namf-comm 服务，覆盕约 60% 的 SBI 调用）
4. **P0**：SBI stream ID 请求/响应配对
5. **P1**：已关联 NF IP + 时间窗口启发式关联（覆盖 nausf/nsmf/npcf 等无 URL SUPI 的调用）
6. **P1**：PFCP 关联（依赖 SMF IP 推断）
7. **P2**：HTTP2 body JSON 解析提取 SUPI（可选增强，覆盖 nausf/nsmf/npcf body 中的 SUPI）
8. **P3**：关联置信度标记

---

## 10. 需要用测试 pcap 验证的关联场景

| 编号 | 场景 | 验证目标 |
|------|------|----------|
| C1 | 单 UE 正常注册 | NGAP/NAS 分组正确，SBI 关联正确 |
| C2 | 单 UE 注册 + PDU Session | PDU Session 分组正确，PFCP 关联正确 |
| C3 | 多 UE 并发注册 | 不同 UE 的帧不会混淆 |
| C4 | UE 注册失败重试 | 同一 UE 的两次尝试正确分离或合并 |
| C5 | 只有 N2 接口抓包 | 优雅降级，标记 SBI 为 not_captured |
| C6 | 只有 SBI 接口抓包 | 优雅降级，标记 NAS 为 not_captured |
