# TraceWeaver 项目交接文档

**交接日期**: 2026-04-15  
**项目版本**: v0.3.0  
**交接人**: AI Assistant  
**状态**: ✅ Phase 1 + Phase 2 (规则引擎) + Phase 3 (LLM 诊断引擎) 完成

---

## 1. 项目概述

TraceWeaver 是一个 5GC/Open5GS 网络包分析工具，通过解析 pcap 文件提取 5G 核心网的关键协议交互，识别网络事件，诊断故障根因。

### 核心能力
- **多协议提取**: NGAP, NAS-5GS, HTTP2 SBI, PFCP
- **会话关联**: UE 会话分组 → PDU 会话组装 → PFCP 流关联
- **事件识别**: 5GMM/5GSM 消息类型映射为结构化事件
- **跨协议关联**: SBI 调用关联 UE，PFCP 关联 PDU Session
- **LLM 智能诊断**: 通过 litellm 统一接口支持 Ollama / OpenAI，3 级 prompt 策略（large/medium/small），规则引擎自动 fallback

---

## 2. 已完成的功能（Phase 1）

### 2.1 CLI 命令（终态入口）

| 命令 | 功能 | 示例 |
|------|------|------|
| `profiles list` | 列出可用 profile | `traceweaver profiles list` |
| `scopes list` | 预览 profile 生成的分析 scope | `traceweaver scopes list file.pcapng --profile open5gs_5gc` |
| `analyze` | 统一分析入口 | `traceweaver analyze file.pcapng --profile open5gs_5gc --compact` |
| `diagnose` | 终态诊断入口 | `traceweaver diagnose file.pcapng --profile open5gs_5gc --compact` |
| `diagnose --model` | LLM 驱动诊断 | `traceweaver diagnose file.pcapng --profile open5gs_5gc --model ollama/qwen3.5:9b` |
| `investigate` | 终态 investigation 入口 | `traceweaver investigate file.pcapng --profile open5gs_5gc` |

### 2.2 核心数据流

```
pcap → analyze_capture(profile="open5gs_5gc")
                      ↓
profiles.open5gs_5gc.extract.records.extract_records()
                      ↓
profiles.open5gs_5gc.assemble.group_ue_sessions()
                      ↓
profiles.open5gs_5gc.assemble.correlate_sbi_to_sessions()
                      ↓
profiles.open5gs_5gc.assemble.build_pdu_sessions_for_ue()
                      ↓
profiles.open5gs_5gc.diagnosis.collect_signals()
                      ↓
profiles.open5gs_5gc.diagnosis.diagnose_session() / llm_diagnose_session()
```

### 2.3 关键算法

1. **UE Session 分组**
   - Key: `(RAN-UE-NGAP-ID, AMF-UE-NGAP-ID)`
   - 处理无 UE ID 的 NAS 帧：单候选时间窗口挂接

2. **SBI 配对**
   - Key: `tcp.stream + http2.streamid`
   - 合并 request/response 为 SBICall

3. **SBI 归属 UE**
   - 高置信度：URL path 中的 SUCI/SUPI
   - 中置信度：单候选时间窗口

4. **PDU 组装**
   - 基于 5GSM 事件的 `pdu_session_id`
   - nsmf-pdusession 按路径 `_{pdu_id}` 或时间窗口归属

5. **PFCP 关联**
   - SMF IP + 时间窗口（首版）

---

## 3. 代码结构

```
traceweaver/
├── __main__.py              # CLI 入口
├── cli.py                   # CLI 命令定义 (6个命令)
├── models/                  # Pydantic 数据模型
│   ├── capture.py           # CaptureInspection
│   ├── events.py            # DetectedEvent, DetectedEventSet
│   ├── records.py         # NormalizedRecord, ExtractedRecordSet
│   ├── sbi.py             # SBICall, SBICallSet
│   ├── sessions.py        # UESession, UESessionSet
│   └── pdu.py             # PDUSessionFlow, PFCPFlow, PDUSessionSet
├── events/                  # 事件识别层
│   └── identify.py        # NAS_MM_EVENT_MAP, NAS_SM_EVENT_MAP
├── ingest/                  # 数据摄入层
│   ├── __init__.py        # 导出 extract_* 函数
│   ├── pcap.py            # inspect_capture
│   ├── records.py         # extract_5gc_records
│   ├── events.py          # extract_5gc_events
│   ├── sbi.py             # extract_sbi_calls
│   ├── sessions.py        # extract_ue_sessions
│   └── pdu.py             # extract_pdu_sessions
├── correlate/             # 关联算法层
│   ├── ue_sessions.py     # group_ue_sessions
│   ├── sbi.py             # pair_sbi_calls, correlate_sbi_to_sessions
│   └── pdu.py             # build_pdu_sessions_for_ue, correlate_pfcp_to_pdu
├── llm/                   # LLM 诊断层
│   ├── __init__.py
│   ├── provider.py        # LLMConfig, LLMProvider (litellm 统一接口)
│   ├── prompts.py         # 3 级 prompt 策略, timeline/signal 格式化
│   └── output.py          # LLMDiagnosisOutput 校验, JSON 提取
├── utils.py               # 公共工具 (parse_optional_int/float)
└── tshark/                # tshark 交互层
    ├── __init__.py
    ├── tools.py           # get_tshark_version, list_tshark_fields
    └── extract.py         # _run_tshark_extract, extract_5gc_records

tests/
├── fixtures/pcap/         # 测试样本 (01-16 场景)
│   ├── 01_registration_success.pcapng
│   ├── 02_registration_and_pdu_session_success.pcapng
│   ├── 03_registration_reject.pcapng
│   ├── 04_authentication_failure.pcapng
│   ├── 05_pdu_session_reject.pcapng
│   ├── 07_pfcp_failure.pcapng
│   ├── 08_sbi_failure.pcapng
│   ├── 09_multi_ue_concurrent.pcapng
│   ├── 10_deregistration.pcapng
│   ├── 11_registration_retry.pcapng
│   ├── 12_service_request.pcapng
│   ├── 13_pdu_session_release.pcapng
│   ├── 15_partial_visibility_multi_host.pcapng
│   ├── 16_truncated_or_lossy_capture.pcapng
│   └── expected_diagnosis.json   # 预期诊断结果
├── test_extract_records.py
├── test_extract_events.py
├── test_extract_sessions.py
├── test_extract_sbi.py
└── test_extract_pdu.py

plan/
├── 5gc-mvp-roadmap.md     # 路线图
├── cross-protocol-correlation.md  # 跨协议关联设计
├── intelligence-first-architecture.md
├── platform-architecture.md
└── test-pcap-checklist.md
```

---

## 4. 关键设计决策

### 4.1 tshark 字段规范化
```python
# occurrence=a + aggregator='|' 会产生 1|1 这样的聚合值
# 我们统一做去重取首值处理
SINGLE_VALUE_FIELDS = { "ngap.RAN_UE_NGAP_ID", "nas_5gs.mm.message_type", ... }
```

### 4.2 受保护 5GSM 消息归属
- 问题：安全模式后的 5GSM 帧没有 NGAP UE ID
- 解决：对无 UE ID 的 nas_5gs 帧，用保守的单候选时间窗口挂接
- 实现位置：`traceweaver/profiles/open5gs_5gc/assemble/ue.py`

### 4.3 SBI URL 中 SUPI 覆盖率
| 服务 | URL 含 SUPI | 说明 |
|------|------------|------|
| nudm-ueau/uecm/sdm | ✅ | URL path 含 SUCI/SUPI |
| nausf-auth | ❌ | SUCI 在 body |
| nsmf-pdusession | ❌ (创建时) | modify 时路径有 _{pdu_id} |
| npcf-* | ❌ | body |

### 4.4 关联策略优先级
1. **直接 identity** (URL path) → 高置信度
2. **单候选时间窗口** → 中置信度
3. **多候选最近时间** → 低置信度 (待实现)

---

## 5. 测试状态

### 5.1 当前测试覆盖

```bash
# 运行测试
python3 -B -m pytest -q

# 当前结果: 99 passed, 42 skipped
```

| 测试文件 | 覆盖场景 |
|----------|----------|
| `test_extract_records.py` | 01/02/03 样本，limit 参数 |
| `test_extract_events.py` | 01/02/03 事件识别 |
| `test_extract_sessions.py` | 01 单 UE, 09 多 UE |
| `test_extract_sbi.py` | 02 SBI 配对，08 SBI 归属 |
| `test_extract_pdu.py` | 02 PDU 建链, 13 Release, 07 PFCP failure |
| `test_correlate_sbi.py` | SBI 配对数值解析，关联 warning 发射 |
| `test_diagnosis.py` | 13 场景端到端诊断 verdict/signal/SBI 路径验证 |
| `test_llm.py` | LLM 提供商抽象、prompt 构建、输出验证、fallback 逻辑 |

### 5.2 预期诊断基线

`tests/fixtures/expected_diagnosis.json` 定义了 15 个场景的期望诊断结果：
- 01: registration_success → OK
- 02: registration_and_pdu_session_success → OK
- 03: registration_reject → FAIL (UE_IDENTITY_CANNOT_BE_DERIVED)
- 04: authentication_failure → FAIL (AKA_MAC_MISMATCH)
- 07: pfcp_failure → FAIL (UPF_UNAVAILABLE)
- 08: sbi_failure → FAIL (UDM_UNAVAILABLE)
- 等等...

---

## 6. LLM 诊断架构

### 6.1 架构概览

```
pcap → 结构化提取 → 信号标注 → LLM 诊断 → 结果校验
                                  ↓ (失败)
                            规则引擎 fallback
```

### 6.2 Provider 层 (litellm)

通过 litellm 统一 Ollama 和 OpenAI API：

```bash
# Ollama (本地)
traceweaver diagnose file.pcapng --model ollama/qwen2.5:14b

# OpenAI
traceweaver diagnose file.pcapng --model gpt-4o --api-key sk-xxx

# 自定义 endpoint
traceweaver diagnose file.pcapng --model openai/qwen-plus --api-base http://xxx --api-key xxx
```

### 6.3 三级 Prompt 策略

| 模型层级 | 代表模型 | Prompt 策略 |
|----------|----------|------------|
| large | gpt-4o, qwen2.5:72b | 开放式分析，minimal hints |
| medium | qwen2.5:14b, gpt-4o-mini | 分步引导 (5 步分析) |
| small | qwen2.5:7b, llama3.1:8b | CoT 模板 + 信号 hints |

### 6.4 输出校验与 Fallback

1. LLM 返回 JSON → Pydantic `LLMDiagnosisOutput` 校验 (verdict/confidence 枚举)
2. JSON 解析失败 → 自动从 markdown code block / 文本中提取
3. 校验失败 → 重试 (max_retries)
4. 全部失败 → 规则引擎 fallback (notes 标注 `llm_fallback`)

---

## 7. 待办事项（下一步）

### 7.1 高优先级

1. **RAG 增强**: 3GPP spec 知识库接入
2. **LLM 评测**: 用 expected_diagnosis.json 做 LLM vs 规则引擎对比评测

### 7.2 中优先级

3. **HTTP2 Body 解析**: nausf-auth/npcf-* body 中的 SUPI 提取
4. **PFCP SEID 配对**: 精细 SEID 级 request/response 配对
5. **CLI 增强**: 输出格式 (table/tree)、诊断报告生成

### 7.3 技术债务

- 时间窗口参数硬编码，可配置化
- `correlate_sbi_to_sessions` 隐式副作用 (ISSUES #5)
- CLI `--limit` 语义对用户有误导 (ISSUES #8)

---

## 7. 环境依赖

```bash
# 系统依赖
tshark >= 4.0
capinfos >= 4.0

# Python 依赖 (pyproject.toml)
python >= 3.11
pydantic >= 2.8
litellm >= 1.40
pytest >= 8  (dev)

# 安装
pip install -e ".[dev]"
```

---

## 8. 快速开始

```bash
# 1. 查看可用 profile
python3 -B -m traceweaver profiles list

# 2. 预览分析 scope
python3 -B -m traceweaver scopes list tests/fixtures/pcap/01_registration_success.pcapng --profile open5gs_5gc --compact

# 3. 运行统一分析
python3 -B -m traceweaver analyze tests/fixtures/pcap/02_registration_and_pdu_session_success.pcapng --profile open5gs_5gc --compact

# 4. 运行 LLM 诊断
python3 -B -m traceweaver diagnose tests/fixtures/pcap/01_registration_success.pcapng --profile open5gs_5gc --model ollama/qwen3.5:9b --compact

# 5. 运行测试
python3 -B -m pytest -q
```

---

## 9. 重要文件速查

| 需求 | 查看文件 |
|------|----------|
| 了解设计思路 | `plan/cross-protocol-correlation.md` |
| 事件映射表 | `traceweaver/profiles/open5gs_5gc/events/identify.py` |
| 模型定义 | `traceweaver/models/*.py` |
| 关联算法 | `traceweaver/profiles/open5gs_5gc/assemble/*.py` |
| CLI 入口 | `traceweaver/cli.py` |
| 测试样本 | `tests/fixtures/pcap/` |
| 预期诊断 | `tests/fixtures/expected_diagnosis.json` |

---

## 10. 已知问题

1. **06_security_mode_reject** 样本尚未采集（计划内）
2. 部分样本需强制 decode-as: `tcp.port==7777,http2`
3. 受保护 5GSM 帧的归属是保守策略，可能漏判（已注释说明）

---

**文档结束**  
交接人签名: AI Assistant  
接收人: 后续开发者
