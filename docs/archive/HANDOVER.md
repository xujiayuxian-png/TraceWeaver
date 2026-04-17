# TraceWeaver 项目交接文档

**交接日期**: 2026-04-16  
**项目版本**: v0.4.0  
**交接人**: AI Assistant  
**状态**: ✅ Phase 1 + Phase 2 (规则引擎) + Phase 3 (LLM 诊断引擎) + Phase 4 (Agentic Investigation Engine) 完成

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

## 3. Investigation Engine (Phase 4 新增)

### 3.1 架构概览

```
pcap → analyze_capture(profile="open5gs_5gc")
              ↓
    build_diagnosis_contexts()
              ↓
    ┌─────────────────────────┐
    │  Investigation Engine   │
    │  (Multi-round loop)       │
    └─────────┬───────────────┘
              ↓
    Round 1: build_plan → execute_tools → evaluate_termination
              ↓ (if continue)
    Round 2: build_plan → execute_tools → evaluate_termination
              ↓
    Final: InvestigationResult with full trace
```

### 3.2 LLM 参与层次

| 阶段 | LLM 作用 | 关键函数 |
|------|---------|---------|
| **Diagnosis** | 主诊断引擎 | `llm_diagnose_session()` |
| **Planner** | hypothesis ranking / tool selection | `_rank_with_llm()` |
| **Termination** | 复核终止决策 + next action synthesis | `reconsider_termination_with_llm()` |

### 3.3 工具集

#### 平台通用工具 (core/agent/tools.py)
- `knowledge_refs` - 知识引用列表
- `evidence_index` - 证据索引

#### Profile 专属工具 (profiles/open5gs_5gc/investigation.py)
- `scope_overview` - Scope 概览
- `visibility_analysis` - 可见性分析
- `evidence_focus` - 证据聚焦
- `signal_focus` - 信号聚焦
- `protocol_drilldown` - 协议下钻
- `frame_targeting` - 帧级定位

### 3.4 CLI 用法

```bash
# 基础 investigation (规则驱动)
traceweaver investigate file.pcapng --profile open5gs_5gc

# 带 LLM 增强的 investigation
traceweaver investigate file.pcapng --profile open5gs_5gc --model ollama/qwen2.5:14b

# 指定 scope 调查
traceweaver investigate file.pcapng --profile open5gs_5gc --scope-id ran-1__amf-2
```

### 3.5 输出结构

```json
{
  "investigations": [{
    "scope_id": "ran-1__amf-2",
    "round_count": 2,
    "plan": {
      "planning_source": "rule|llm",
      "tool_sequence": [...]
    },
    "executed_tools": [...],
    "tool_results": [...],
    "termination": {
      "status": "completed|continue",
      "source": "rule|llm",
      "reasoning": "...",
      "next_actions": [...]
    },
    "steps": [
      {"action": "build_plan", ...},
      {"action": "run_tool", ...},
      {"action": "terminate_investigation", ...}
    ]
  }]
}
```

---

## 4. 代码结构

```
traceweaver/
├── core/
│   ├── agent/               # Investigation Engine (Phase 4)
│   │   ├── engine.py        # investigate_capture() 主入口
│   │   ├── planner.py       # build_investigation_plan(), evaluate_termination(), reconsider_termination_with_llm()
│   │   ├── prompts.py       # planner + termination prompts
│   │   ├── tools.py         # 工具注册表
│   │   └── result.py        # InvestigationResult, ScopeInvestigation, InvestigationStep
│   ├── analysis/            # 统一分析入口
│   ├── contracts/           # 平台契约 (Scope, Signal, Evidence, Diagnosis, Visibility)
│   ├── profile/             # Profile 运行时
│   └── llm/                 # LLM Provider
├── profiles/
│   └── open5gs_5gc/         # 首个官方 Profile
│       ├── profile.py       # Open5GS5GCProfile 实现
│       ├── extract/         # 记录抽取
│       ├── assemble/        # 会话组装 (UE/SBI/PDU)
│       ├── events/          # 事件识别
│       ├── diagnosis/       # 诊断引擎
│       └── investigation.py # Profile 专属调查工具
└── cli.py                   # 终态 CLI
```

---

## 5. 关键算法

### 5.1 UE Session 分组
- Key: `(RAN-UE-NGAP-ID, AMF-UE-NGAP-ID)`
- 处理无 UE ID 的 NAS 帧：单候选时间窗口挂接

### 5.2 SBI 配对
- Key: `tcp.stream + http2.streamid`
- 合并 request/response 为 SBICall

### 5.3 SBI 归属 UE
- 高置信度：URL path 中的 SUCI/SUPI
- 中置信度：单候选时间窗口

### 5.4 PDU 组装
- 基于 5GSM 事件的 `pdu_session_id`
- nsmf-pdusession 按路径 `_{pdu_id}` 或时间窗口归属

### 5.5 PFCP 关联
- SMF IP + 时间窗口（首版）

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

## 7. 测试状态

### 7.1 当前测试覆盖

```bash
# 运行测试
python3 -B -m pytest -q

# 当前结果: 107 passed, 42 skipped
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
| `test_investigation.py` | Investigation engine: 多轮 loop、scope_id、LLM planner、LLM termination |

### 7.2 预期诊断基线

`tests/fixtures/expected_diagnosis.json` 定义了 15 个场景的期望诊断结果：
- 01: registration_success → OK
- 02: registration_and_pdu_session_success → OK
- 03: registration_reject → FAIL (UE_IDENTITY_CANNOT_BE_DERIVED)
- 04: authentication_failure → FAIL (AKA_MAC_MISMATCH)
- 07: pfcp_failure → FAIL (UPF_UNAVAILABLE)
- 08: sbi_failure → FAIL (UDM_UNAVAILABLE)
- 等等...

---

## 8. 待办事项（下一步）

### 8.1 高优先级

1. **RAG 增强**: 3GPP spec 知识库接入
2. **LLM 评测**: 用 expected_diagnosis.json 做 LLM vs 规则引擎对比评测

### 8.2 中优先级

3. **HTTP2 Body 解析**: nausf-auth/npcf-* body 中的 SUPI 提取
4. **PFCP SEID 配对**: 精细 SEID 级 request/response 配对
5. **CLI 增强**: 输出格式 (table/tree)、诊断报告生成

### 8.3 技术债务

- 时间窗口参数硬编码，可配置化
- `correlate_sbi_to_sessions` 隐式副作用 (ISSUES #5)
- CLI `--limit` 语义对用户有误导 (ISSUES #8)

---

## 9. 环境依赖

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

## 10. 快速开始

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

## 11. 重要文件速查

| 需求 | 查看文件 |
|------|----------|
| 了解设计思路 | `plan/cross-protocol-correlation.md`, `redo.md` |
| 事件映射表 | `traceweaver/profiles/open5gs_5gc/events/identify.py` |
| 模型定义 | `traceweaver/core/contracts/*.py`, `traceweaver/models/*.py` |
| 关联算法 | `traceweaver/profiles/open5gs_5gc/assemble/*.py` |
| Investigation Engine | `traceweaver/core/agent/` |
| CLI 入口 | `traceweaver/cli.py` |
| 测试样本 | `tests/fixtures/pcap/` |
| 预期诊断 | `tests/fixtures/expected_diagnosis.json` |

---

## 12. 已知问题

1. **06_security_mode_reject** 样本尚未采集（计划内）
2. 部分样本需强制 decode-as: `tcp.port==7777,http2`
3. 受保护 5GSM 帧的归属是保守策略，可能漏判（已注释说明）

---

**文档结束**  
交接人签名: AI Assistant  
接收人: 后续开发者
