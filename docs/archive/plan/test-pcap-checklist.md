# 测试 PCAP 采集清单

## 1. 环境要求

- **核心网**：Open5GS（最新稳定版）
- **RAN 模拟**：UERANSIM
- **抓包点**：建议在 AMF 所在主机抓包（可同时看到 N2/SBI/PFCP）
- **抓包工具**：tcpdump 或 tshark
- **抓包过滤**：不过滤，全量抓取（后续在分析时过滤）

### 1.1 抓包命令参考

```bash
# 在 AMF 主机上全量抓包
sudo tcpdump -i any -w test_scenario_name.pcap

# 或使用 tshark
sudo tshark -i any -w test_scenario_name.pcap
```

### 1.2 环境配置注意事项

- 确保 Open5GS 各 NF 的 SBI 接口使用 HTTP2（不是 HTTP/1.1）
- 确保 PFCP 通信可见（如果 UPF 在不同主机，需要在 SMF 侧也抓包）
- 建议将各 NF 分别监听在不同 IP 或端口，便于后续按 IP 区分 NF
- 如果 AMF / SMF / UPF 分布在多台主机，建议保留多点抓包，避免默认假设“单机全可见”
- 尽量保留原始时间戳与主机信息，便于后续分析跨主机时间偏差

---

## 2. 必须采集的场景（P0）

### 2.1 正常注册成功

**文件名**：`01_registration_success.pcap`

**操作步骤**：
1. 启动 Open5GS 所有 NF
2. 启动 UERANSIM gNB
3. 启动 UERANSIM UE，执行注册
4. 确认注册成功后停止抓包

**预期包含的消息**：
- NGAP: InitialUEMessage, DownlinkNASTransport, UplinkNASTransport, InitialContextSetupRequest/Response
- NAS: Registration Request, Authentication Request/Response, Security Mode Command/Complete, Registration Accept/Complete
- SBI: nausf-auth, nudm-uecm, nudm-sdm, npcf-am-policy-control
- 无 PFCP（仅注册，不建 PDU Session）

**验证目标**：
- 基线数据，确认完整流程可被正确关联
- 验证 NGAP/NAS 分组
- 验证 SBI SUPI/SUCI 关联

---

### 2.2 正常注册 + PDU Session 建立成功

**文件名**：`02_registration_and_pdu_session_success.pcap`

**操作步骤**：
1. 启动全套环境
2. UE 注册
3. UE 建立 PDU Session（UERANSIM 默认会自动建立）
4. 确认 PDU Session 成功后停止抓包

**预期包含的消息**：
- 以上注册流程所有消息
- NAS: PDU Session Establishment Request/Accept
- SBI: nsmf-pdusession (SM Context Create), npcf-smpolicycontrol, nudm-sdm
- PFCP: Session Establishment Request/Response

**验证目标**：
- PDU Session 级关联
- SBI ↔ PFCP 跨协议关联
- SMF IP 推断

---

### 2.3 注册被拒绝（Registration Reject）

**文件名**：`03_registration_reject.pcap`

**触发方式**（任选一种）：
- 使用未配置的 IMSI 进行注册
- 修改 Open5GS subscriber 数据库，删除目标 UE 的订阅
- 配置 PLMN 不匹配

**预期包含的消息**：
- NAS: Registration Request → Registration Reject (with 5GMM cause code)
- SBI: 可能有 nausf-auth 失败或 nudm 查询返回错误

**验证目标**：
- Reject cause code 提取
- 信号标注器对 REJECT_CAUSE 的标注
- 不完整流程的优雅处理

---

### 2.4 鉴权失败（Authentication Failure）

**文件名**：`04_authentication_failure.pcap`

**触发方式**：
- 修改 UERANSIM 侧的 key/OPC 使其与 Open5GS 不匹配
- 或修改 Open5GS subscriber 的 key

**预期包含的消息**：
- NAS: Registration Request → Authentication Request → Authentication Failure
- SBI: nausf-auth 调用，可能返回错误
- 流程在鉴权阶段终止

**验证目标**：
- 鉴权失败事件识别
- 流程跟踪器检测到停在 AUTH_STARTED 阶段
- SBI 错误关联

---

### 2.5 PDU Session 建立被拒绝

**文件名**：`05_pdu_session_reject.pcap`

**触发方式**：
- 修改 subscriber 的 session 配置（如不允许的 DNN）
- 或配置 SMF 拒绝 PDU Session

**预期包含的消息**：
- 正常注册成功
- NAS: PDU Session Establishment Request → PDU Session Establishment Reject (with 5GSM cause)
- SBI: nsmf-pdusession 可能返回错误

**验证目标**：
- PDU Session Reject cause code 提取
- 注册成功但 Session 失败的混合场景

---

## 3. 建议采集的场景（P1）

### 3.1 安全模式失败

**文件名**：`06_security_mode_reject.pcap`

**触发方式**：
- 修改 UE 安全能力配置，使其与网络侧不兼容
- 这个比较难触发，如果无法复现可以暂时跳过

**验证目标**：
- Security Mode Reject/流程卡住

---

### 3.2 PFCP Session 建立失败

**文件名**：`07_pfcp_failure.pcap`

**触发方式**：
- 关闭 UPF 后尝试建立 PDU Session
- 或修改 UPF 配置使其拒绝 PFCP

**预期包含的消息**：
- 注册成功
- NAS: PDU Session Establishment Request
- SBI: nsmf-pdusession 触发
- PFCP: Session Establishment Request 但无 Response（或 Response 带失败 cause）
- 最终 NAS: PDU Session Establishment Reject

**验证目标**：
- PFCP 超时/失败检测
- 下游失败导致上游 Reject 的链路还原

---

### 3.3 SBI 调用失败

**文件名**：`08_sbi_failure.pcap`

**触发方式**：
- 关闭 AUSF 或 UDM 后尝试注册
- 期望 AMF 的 SBI 调用超时或返回 5xx

**验证目标**：
- HTTP2 错误码检测
- SBI 失败 → NAS 流程终止的因果链

---

### 3.4 多 UE 并发注册

**文件名**：`09_multi_ue_concurrent.pcap`

**操作步骤**：
1. 配置 2-3 个不同 IMSI 的 UE
2. 几乎同时发起注册

**验证目标**：
- 多 UE Session 正确分离
- SUPI/SUCI 关联不混淆

---

### 3.5 UE 去注册

**文件名**：`10_deregistration.pcap`

**操作步骤**：
1. UE 正常注册 + PDU Session
2. UE 主动去注册（或关闭 UERANSIM UE）

**验证目标**：
- Deregistration 事件识别
- UE Context Release 检测

---

## 4. 进阶场景（P2，可后期补充）

### 4.1 UE 注册后重试

**文件名**：`11_registration_retry.pcap`

**操作**：UE 注册失败后再次尝试注册

**验证目标**：
- 同一 UE 多次注册尝试的区分
- RAN-UE-NGAP-ID 可能变化

### 4.2 Service Request

**文件名**：`12_service_request.pcap`

**操作**：UE 进入 idle 后重新发起 Service Request

### 4.3 PDU Session 释放

**文件名**：`13_pdu_session_release.pcap`

**操作**：手动触发 PDU Session 释放

### 4.4 Handover 相关

**文件名**：`14_handover.pcap`

**说明**：UERANSIM 可能不支持完整 handover，可后期用实际设备补充

### 4.5 分布式抓包 / 可见性不完整

**文件名**：`15_partial_visibility_multi_host.pcapng`

**说明**：
- 只抓到 AMF 主机 N2 + 部分 SBI
- 或 AMF / SMF 分别抓包，后续再合并分析

**验证目标**：
- 系统能把缺失链路明确标记为 `not_captured`
- 不因只看到局部协议而给出伪完整因果链

### 4.6 脏数据 / 截断抓包

**文件名**：`16_truncated_or_lossy_capture.pcap`

**说明**：
- 人为提前停止抓包
- 或使用会发生截断/丢包的抓包配置

**验证目标**：
- 验证时间线优雅降级
- 验证 `limitations` / `not_captured` / `ambiguous` 输出

---

## 5. 采集清单汇总

| 编号 | 场景 | 优先级 | 文件名 |
|------|------|--------|--------|
| 01 | 正常注册成功 | P0 | `01_registration_success.pcap` |
| 02 | 注册 + PDU Session 成功 | P0 | `02_registration_and_pdu_session_success.pcap` |
| 03 | 注册被拒绝 | P0 | `03_registration_reject.pcap` |
| 04 | 鉴权失败 | P0 | `04_authentication_failure.pcap` |
| 05 | PDU Session 被拒绝 | P0 | `05_pdu_session_reject.pcap` |
| 06 | 安全模式失败 | P1 | `06_security_mode_reject.pcap` |
| 07 | PFCP 建立失败 | P1 | `07_pfcp_failure.pcap` |
| 08 | SBI 调用失败 | P1 | `08_sbi_failure.pcap` |
| 09 | 多 UE 并发 | P1 | `09_multi_ue_concurrent.pcap` |
| 10 | UE 去注册 | P1 | `10_deregistration.pcap` |
| 11 | 注册重试 | P2 | `11_registration_retry.pcap` |
| 12 | Service Request | P2 | `12_service_request.pcap` |
| 13 | PDU Session 释放 | P2 | `13_pdu_session_release.pcap` |
| 14 | Handover | P2 | `14_handover.pcap` |
| 15 | 分布式抓包 / 可见性不完整 | P2 | `15_partial_visibility_multi_host.pcapng` |
| 16 | 脏数据 / 截断抓包 | P2 | `16_truncated_or_lossy_capture.pcap` |

---

## 6. 采集后验证

每份 pcap 采集后，建议用以下命令快速验证内容完整性：

```bash
# 检查是否包含目标协议
tshark -r file.pcap -Y "ngap" -c 1
tshark -r file.pcap -Y "nas-5gs" -c 1
tshark -r file.pcap -Y "http2" -c 1
tshark -r file.pcap -Y "pfcp" -c 1

# 查看 NAS 消息类型分布
tshark -r file.pcap -Y "nas-5gs" -T fields -e nas_5gs.mm.message_type -e nas_5gs.sm.message_type | sort | uniq -c

# 查看 NGAP 过程类型分布
tshark -r file.pcap -Y "ngap" -T fields -e ngap.procedureCode | sort | uniq -c

# 查看 SBI 路径
tshark -r file.pcap -Y "http2.headers.path" -T fields -e http2.headers.path | sort | uniq -c

# 查看 PFCP 消息
tshark -r file.pcap -Y "pfcp" -T fields -e pfcp.msg_type | sort | uniq -c

# 验证 SUCI 提取（从 NAS Registration Request）
tshark -r file.pcap -Y "nas_5gs.mm.message_type == 65" -T fields -e nas_5gs.mm.suci.scheme_output -e nas_5gs.mm.type_of_identity

# 验证 SUPI 在 SBI URL path 中的出现（nudm-*/namf-comm 的 URL 包含 SUPI）
tshark -r file.pcap -Y "http2.headers.path contains \"imsi-\" || http2.headers.path contains \"suci-\"" -T fields -e http2.headers.path | sort | uniq -c

# 验证无 SUPI 的 SBI 调用（nausf/nsmf/npcf URL 中不含 SUPI，需要 IP+时间窗口关联）
tshark -r file.pcap -Y "http2.headers.path contains \"ue-authentications\" || http2.headers.path contains \"sm-contexts\" || http2.headers.path contains \"policies\"" -T fields -e ip.src -e ip.dst -e http2.headers.path | head -20

# 验证 HTTP2 SBI 请求/响应配对
tshark -r file.pcap -Y "http2" -T fields -e http2.streamid -e http2.headers.method -e http2.headers.status -e http2.headers.path | head -30
```

---

## 7. 文件存放

建议将测试 pcap 放在：

```text
TraceWeaver/
  tests/
    fixtures/
      pcap/
        01_registration_success.pcap
        02_registration_and_pdu_session_success.pcap
        ...
```

并在 `.gitignore` 中 **不忽略** 这些文件（它们是测试的关键资产，应随代码管理）。
注意单个文件大小，如果超过 10MB 考虑使用 Git LFS。

如果抓包包含真实 `IMSI` / `SUCI` / 内网地址等敏感信息，建议优先做脱敏后再入库。
对于无法公开提交的大文件或敏感样本，建议与公开测试集分层管理，而不是全部直接进入主仓库。
