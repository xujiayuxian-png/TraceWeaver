# 5GC 测试抓包台账

更新时间：2026-04-14

## 1. 使用说明

本文档记录当前已经保存到 `tests/fixtures/pcap/` 的抓包文件、场景语义、质量判断与关键证据，避免后续遗忘或误用。

判定约定：

- **正式**：可直接作为 TraceWeaver MVP/P1/P2 评测输入
- **可用但需说明**：可用，但语义不够教科书式，需要在评测元数据里加说明
- **候选**：有参考价值，但暂不建议作为 canonical 样本

## 2. 正式 / canonical 样本

| 文件 | 场景 | 状态 | 关键证据 | 备注 |
|------|------|------|----------|------|
| `01_registration_success.pcapng` | 纯注册成功 | 正式 | UE 日志显示 `Initial Registration is successful`，未自动发起 PDU | 纯注册基线 |
| `02_registration_and_pdu_session_success.pcapng` | 注册 + PDU 成功 | 正式 | 注册成功，`PDU Session Establishment Accept` 成功 | 完整成功链路基线 |
| `03_registration_reject.pcapng` | 注册被拒绝 | 正式 | UE 日志显示 `Initial Registration failed [UE_IDENTITY_CANNOT_BE_DERIVED_FROM_NETWORK]` | 用未开户 IMSI 触发 |
| `04_authentication_failure.pcapng` | 鉴权失败 | 正式 | `AUTN validation MAC mismatch`，`Authentication Failure (MAC failure)`，`Authentication Reject` | 失败原因非常单一 |
| `05_pdu_session_reject.pcapng` | PDU 建立失败 | 可用但需说明 | UE 侧反复 `SM forwarding failure` / `PAYLOAD_NOT_FORWARDED` | 更接近 forwarding failure，而非教科书式 reject |
| `05_pdu_session_reject_clean.pcapng` | PDU 建立失败（重采） | 可用但需说明 | 仍表现为 `PAYLOAD_NOT_FORWARDED` | 可作为 05 的补充样本 |
| `07_pfcp_failure.pcapng` | PFCP 建立失败 | 正式 | 注册成功；PDU 建立多次 `T3580 expiry`；最终 `no response from the network after 5 attempts` | 采集前需先停 `5gswatching.timer` 再停 `UPF` |
| `08_sbi_failure.pcapng` | SBI 调用失败 | 正式 | 在 `tcp.port==7777` 强制 decode 为 `http2` 后，可见 `POST /nausf-auth/v1/ue-authentications`、`GET /nnrf-disc/v1/nf-instances?target-nf-type=UDM&requester-nf-type=AUSF`；UE 侧 `PAYLOAD_NOT_FORWARDED` | canonical 来源为 `08_sbi_failure_retry_udm.pcapng` |
| `09_multi_ue_concurrent.pcapng` | 多 UE 并发注册 | 正式 | 三个 IMSI 几乎同时注册成功 | 用于验证会话隔离与关联鲁棒性 |
| `10_deregistration.pcapng` | UE 去注册 | 正式 | CLI 触发 `deregister normal`；UE 日志出现 `De-registration accept received` 与 `De-registration is successful` | canonical 来源为 `10_deregistration_cli.pcapng` |
| `11_registration_retry.pcapng` | 注册重试 | 正式 | 同一 IMSI 先 `Authentication failure` / `Authentication reject`，后重试成功 | 适合验证多次尝试链路 |
| `12_service_request.pcapng` | Service Request | 正式 | UE 进入 `CM-IDLE` 后再次触发业务，日志出现 `Sending Service Request` 与 `Service Accept received` | canonical 来源为 `12_service_request_candidate.pcapng` |
| `13_pdu_session_release.pcapng` | PDU Session 释放 | 正式 | 包含 `PFCP Session Deletion Request/Response`，UE 侧有 `PDU Session Release Request` / `Release Command` | 当前最好版本仍是原始版 |
| `15_partial_visibility_multi_host.pcapng` | 分布式抓包 / 可见性不完整 | 正式 | 通过限制远端抓包仅保留 `38412/7777` 端口，只看到 N2 + SBI，不含完整 PFCP 细节；适合验证 `not_captured/limitations` | 需用 `tshark -d tcp.port==7777,http2` 观察 SBI |
| `16_truncated_or_lossy_capture.pcapng` | 截断/不完整抓包 | 正式 | 抓包人为提前停止，链路天然不完整 | 用于验证 `limitations/not_captured/ambiguous` |

## 3. 候选 / 中间样本

| 文件 | 当前判断 | 说明 |
|------|----------|------|
| `06_security_mode_reject_candidate.pcapng` | 候选 | 实际表现为 `UE_SECURITY_CAP_MISMATCH -> Registration Reject` |
| `06_security_mode_reject_ia2_off_candidate.pcapng` | 候选 | 只关 `IA2` 仍可成功注册，未打出目标场景 |
| `06_security_mode_reject_ia3_only_candidate.pcapng` | 候选 | 仅保留 `IA3` 仍表现为 `UE_SECURITY_CAP_MISMATCH -> Registration Reject` |
| `07_pfcp_failure_candidate.pcapng` | 中间样本 | 未先停看门狗，UPF 被拉起，PDU 最终成功 |
| `07_pfcp_failure_retry.pcapng` | 中间样本 | 已能看到 T3580 超时，但不如 long 版完整 |
| `07_pfcp_failure_long.pcapng` | 中间样本 | 质量很好，已复制为 canonical `07_pfcp_failure.pcapng` |
| `08_sbi_failure_candidate.pcapng` | 旧候选 | 未先停看门狗，样本不稳定 |
| `08_sbi_failure_retry_ausf.pcapng` | 强候选 | 停 AUSF 后，注册失败并出现 `PAYLOAD_NOT_FORWARDED` |
| `08_sbi_failure_retry_udm.pcapng` | 中间样本 | 已升为 canonical `08_sbi_failure.pcapng` |
| `10_deregistration_cli.pcapng` | 中间样本 | 已升为 canonical `10_deregistration.pcapng` |
| `12_service_request_candidate.pcapng` | 中间样本 | 已升为 canonical `12_service_request.pcapng` |
| `13_pdu_session_release_clean.pcapng` | 中间样本 | 手工触发建立/释放，时序不如原始版稳定 |
| `13_pdu_session_release_manual.pcapng` | 中间样本 | release 时点仍不够干净 |

## 4. 关键环境事实

### 4.1 看门狗

`ailink5gs` 存在统一看门狗：

- `5gswatching.timer`
- `5gswatching.service`
- `/opt/ailink5gs/bin/5gs_watching.sh`

它会统一监控：

- `nrf`
- `udr`
- `udm`
- `ausf`
- `bsf`
- `nssf`
- `pcf`
- `smf`
- `upf`
- `amf`

如果任一网元异常，会触发 `restart_5gs`。

因此，要稳定打挂任一 NF，必须先执行：

```bash
sudo systemctl stop 5gswatching.timer
```

之后再 stop 目标 NF。

### 4.2 SBI 端口

`ailink5gs` 默认 SBI 端口是 `7777`。

常见监听示例：

- `127.0.0.11:7777` -> `ailink5gs-ausfd`
- `127.0.0.12:7777` -> `ailink5gs-udmd`
- `127.0.0.5:7777` -> `ailink5gs-amfd`
- `127.0.0.4:7777` -> `ailink5gs-smfd`

抓包分析时如果 `http2` 没自动识别，应优先用：

```bash
tshark -d tcp.port==7777,http2 -r file.pcapng -Y 'http2'
```

## 5. 当前未正式完成项

- `06_security_mode_reject`
  - 目前多次尝试都落成 `UE_SECURITY_CAP_MISMATCH -> Registration Reject`
  - 尚未拿到真正教科书式的 `Security Mode Reject`

- `14_handover`
  - 目前未采
  - UERANSIM 对完整 handover 支持有限

## 6. 推荐使用顺序

优先给 TraceWeaver MVP 用的样本：

1. `01_registration_success.pcapng`
2. `02_registration_and_pdu_session_success.pcapng`
3. `03_registration_reject.pcapng`
4. `04_authentication_failure.pcapng`
5. `07_pfcp_failure.pcapng`
6. `08_sbi_failure.pcapng`
7. `09_multi_ue_concurrent.pcapng`
8. `10_deregistration.pcapng`
9. `11_registration_retry.pcapng`
10. `12_service_request.pcapng`
11. `13_pdu_session_release.pcapng`
12. `15_partial_visibility_multi_host.pcapng`
13. `16_truncated_or_lossy_capture.pcapng`
