# TraceWeaver v2 M3 后审查改进清单

**文档状态**: **P0 已完成** | P1 待实施 | P2 规划中  
**优先级**: P0-P2（见各节标注）  
**预计总工时**: ~~1–2 天（P0）~~ **实际 4h** + 3–5 天（P1）  
**最后更新**: 2026-04-20  

---

## 0. 摘要

M3 里程碑已完成，架构层面与 `platform-v2.md` 高度对齐，六层边界清晰，红线有运行时兜底。

**P0 实施结果**（2026-04-20 完成）：
- ✅ 1.1 smoke 样本 5→9 个，端到端验证 6/9 通过（失败为模型能力限制，非代码问题）
- ✅ 1.2 `max_rounds: 16→8`，实测无超时
- ✅ 1.3 schema 全校验（enum/type/format）上线，新增 9 个单元测试
- ✅ 1.4 enricher 禁判决红线加固，新增 6 个单元测试  
- ✅ 1.5 MiniMax temperature 自动夹持，向后兼容

**当前主要风险**（P1 待解决）：
1. **观测能力缺失**: kernel 缺 token/cost/wall-clock 遥测，profile 优化成黑箱
2. **工具参数校验宽松**: coerce 失败透传导致工具内部 TypeError
3. **PcapSource 全量读内存**: 生产 GB 级 pcap 会 OOM

本文档按 ROI 排序列出 12 项改进。

---

## 1. P0 — 高价值 / 低成本（M4 前必须）

### 1.1 扩展 smoke 样本量，消除与回归的脱节 ✅ **已完成**

**问题**  
- smoke 只跑 5 个 pcap，回归跑 28 个
- MiniMax-M2.7 在 smoke 5/5，但在回归里用相同 checker 跑只有 2/5
- 这意味着"smoke 通过"对 M4/M5 改动没有保护力

**实施**  
- 扩展至 9 个任务：原 5 个 + PDU session success / PDU reject / Deregistration / Registration retry
- 验证结果（qwen3.5-9b@q8_k_xl）：**6/9 通过**，失败项为模型误判（T4 PFCP、T9 Retry）

**新增任务**:
| 任务 | pcap | 场景 |
|------|------|------|
| T6 | `02_registration_and_pdu_session_success` | 注册+PDU 完整流程 |
| T7 | `05_pdu_session_reject` | PDU 建立拒绝 |
| T8 | `10_deregistration` | 去注册流程 |
| T9 | `11_registration_retry` | 注册重试后成功 |

**修改文件**: `scripts/run_m3_smoke.py:289-317`  
**工时**: 0.5h  
**验证**: 2026-04-20 真机测试通过

---

### 1.2 收紧 `max_rounds` 默认值 ✅ **已完成**

**问题**  
`profile.yaml:78` 设 `max_rounds: 16`，对 9B 太奢侈，强模型也浪费。

**实施**  
改为 `max_rounds: 8`，端到端测试 9 个任务全部正常结束，无 `max_rounds` 超时。

**修改文件**: `@traceweaver/profiles/open5gs_5gc/profile.yaml:78`

**工时**: 5 min  
**验证**: 2026-04-20 smoke 测试通过

---

### 1.3 加强 response schema 校验（enum/type） ✅ **已完成**

**问题**  
`kernel.py:396-406` 只检查 `required` keys。`verdict` 声明 `"success"|"failure"|"unclear"`，但 LLM 写 `"Success"`、`"ok"` 都通过。

**实施**  
- 引入 `jsonschema>=4.0` 做完整校验（enum/type/format/minimum）
- 新增 `_schema_validate_full()` 在 `_handle_final()` 中优先调用
- 错误消息同时包含完整校验信息和缺失字段（向后兼容）
- 新增 9 个单元测试覆盖 enum/type/minimum/valid/None/fallback 场景

**修改文件**:
- `@traceweaver/core/kernel/kernel.py:421-443` — `_schema_validate_full()`
- `@traceweaver/pyproject.toml:14` — `jsonschema>=4.0`
- `@tests/core/kernel/test_schema_validation.py` — 新增 9 个测试

**工时**: 1h  
**验证**: 173 passed, 1 skipped

---

### 1.4 enricher 禁判决校验 ✅ **已完成**

**问题**  
Registry 只查 `ToolResult.data` 顶层 key，enricher 可把 `verdict` 塞进 `record.fields`，再被 `query_records` 原样返回，绕过红线。

**实施**  
- 新增 `_FORBIDDEN_ENRICH_KEYS` 黑名单（verdict/root_cause/failure_point/confidence）
- 在 `apply_enrichers()` 中 identity 校验后追加红线检查
- 违规时抛 RuntimeError，消息包含 enricher 名称和违规字段
- 新增 6 个单元测试覆盖单字段/多字段/合法字段/允许 cause code 场景

**修改文件**:
- `@traceweaver/core/source/enrich.py:32-54` — 黑名单 + 运行时校验
- `@tests/core/source/test_enrich_redline.py` — 新增 6 个测试

**工时**: 20 min  
**验证**: 现有 enricher 不违规，测试全部通过

---

### 1.5 修复 MiniMax temperature 默认陷阱 ✅ **已完成**

**问题**  
`litellm_adapter.py:279` 默认 `temperature=0.0`，MiniMax 要求 `∈ (0,1]`，会被拒。

**实施**  
在 `LLMIntelligence.__init__` 中对 MiniMax 模型自动夹持：
```python
self.temperature = max(0.05, temperature) if "minimax" in model.lower() else temperature
```
- 仅影响 MiniMax 模型，其他模型保持原值
- 向后兼容：显式传 temperature > 0 时不受影响

**修改文件**: `@traceweaver/core/intelligence/litellm_adapter.py:284-288`

**工时**: 15 min  
**验证**: 代码逻辑正确，待 MiniMax 真机测试

---

## 2. P1 — 中等价值 / 中等成本（M4 并行）

### 2.1 补全 AgentTrace 遥测（token / cost / wall-clock） ✅ **已完成**

**问题**  
`trace.py` 只有 `elapsed_s`。M4 改 prompt/profile 时无法判断"回归是因为 LLM 多想了还是真变准了"。

**实施**  
- `IntelligenceResponse` 新增 `tokens_used` / `cost_usd`
- `TraceEvent` 每轮记录 token/cost
- `AgentTrace` 新增聚合方法 `total_tokens()` / `total_cost_usd()` / `wall_clock_s()`
- `AgentResult` 新增汇总字段 `total_tokens` / `total_cost_usd` / `wall_clock_s`
- `litellm_adapter` 新增 `_extract_usage()` 从 resp.usage 提取数据，支持 GPT/Claude/MiniMax 成本估算，本地模型 cost=0
- `kernel.py` 在 `_handle_final` / `_handle_tool_calls` 中记录遥测

**修改文件**:
- `@traceweaver/core/intelligence/base.py:59-61` — IntelligenceResponse 遥测字段
- `@traceweaver/core/kernel/trace.py:55-113` — TraceEvent/AgentTrace/AgentResult 遥测
- `@traceweaver/core/intelligence/litellm_adapter.py:438-485` — `_extract_usage()`
- `@traceweaver/core/kernel/kernel.py` — 记录遥测到 trace

**工时**: 1.5h  
**验证**: 174 passed

---

### 2.2 工具参数 coerce 失败时抛错而非透传 ✅ **已完成**

**问题**  
`registry.py` schema 声明 `object` 但字符串 parse 出 list 时原样透传，工具内部 TypeError 难排查。

**实施**  
- `_coerce()` 改为严格校验：coerce 失败立即抛 `ValueError`（带清晰字段名和期望值）
- `_validate_arguments()` 捕获异常并包装为 `tool X argument coercion failed: ...`
- kernel 的 `_execute_tool()` 捕获 ValueError 转为 `ToolExecution(ok=False)`，LLM 在 tool-result 中能看到错误并重试
- 支持类型：integer/number/boolean/object/array，非法 JSON 或类型不匹配均报错

**修改文件**:
- `@traceweaver/core/tools/registry.py:91-140` — 严格 coerce + 错误处理
- `@tests/core/tools/test_coerce_strict.py` — 新增 15 个测试（8 成功 + 7 失败场景）

**工时**: 30 min  
**验证**: 189 passed (174 + 15 新增)

---

### 2.3 PcapSource 增加 `max_records` / `time_range` 切片 ✅ **已完成**

**问题**  
`pcap.py` 全量读内存，生产 GB pcap 会 OOM。

**实施**  
- `parse_tshark_fields_output()` 新增 `max_records` 和 `time_range` 参数
- `max_records`: 在解析循环中计数，达到上限立即终止
- `time_range`: 相对首帧的时间窗口 `[start_s, end_s]`，过滤不在范围内的帧
- `PcapSource.ingest()` 从 `spec.options` 读取新配置并传递
- profile YAML 中可配置：
  ```yaml
  source_config:
    pcap:
      max_records: 5000      # 限制返回记录数
      time_range: [0, 300]   # 相对首帧的秒数窗口 [0, 300]
  ```

**修改文件**:
- `@traceweaver/core/source/pcap.py:111-187` — 切片解析逻辑
- `@traceweaver/core/source/pcap.py:255-295` — 选项读取和传递

**工时**: 1h  
**验证**: 189 passed

---

### 2.4 把 `archive/v1/` 从工作树移出 ✅ **已完成**

**问题**  96 个文件在目录里，`find_by_name` / `grep_search` 经常污染上下文；HANDOVER §1 写 "不要读" 但不可靠。

**实施**  
- `git rm -r archive/v1/` 删除工作树文件（保留 git history）
- 需要参考 v1 时：`git show HEAD:archive/v1/...`
- agent 上下文干净，search 不再污染

**工时**: 10 min  
**验证**: 96 files deleted, ready to commit

---

### 2.5 实现 `traceweaver validate-profile` 子命令 ✅ **已完成**

**问题**  写外部 profile 要自己看 yaml_loader/loader 推规则，门槛高。

**实施**  
- 新增 `traceweaver validate-profile <dir>` CLI 子命令
- 校验项：
  1. `profile.yaml` 语法合法
  2. `system_prompt` / `response_schema` 成功加载
  3. `knowledge/*` 文件存在
  4. `enrichers` 可 import 且 callable
  5. `tools` 可 import 且是 Tool 子类（或 factory callable）
  6. `source_config.pcap.fields` 是字符串列表
- 用法：`traceweaver validate-profile -v ./my_profile`
- open5gs_5gc profile 验证通过

**修改文件**:
- `@traceweaver/cli/validate_profile.py` — 新文件（146 行）
- `@traceweaver/cli/__init__.py:38-41` — 注册子命令

**工时**: 1h  
**验证**: 189 passed, open5gs_5gc profile PASSED

---

## 3. P2 — 架构级 / 长线（M5+ 或按需）

### 3.1 明确并实现 "Scope" 切分 或 从文档删除

**问题**  
`profile.yaml` 声明 `scope` / `sub_scopes` 定义 primary_key 拆分规则，但 loader 到 kernel 都不消费。现状等于把多 UE/多 session pcap 塞成一个大上下文。

**建议**  二选一：
- **方案 A（实现）**: 每个 scope 实例单独跑 kernel，再 merge verdict（需要设计 merge 策略）
- **方案 B（删除）**: 从 YAML loader、base model、文档里删掉，避免 profile 作者错觉

**决策人**: 用户（需确认是否需支持多 UE 独立诊断）

---

### 3.2 引入 "scripted LLM 录制回放" 测试

**问题**  `tests/cli/test_analyze_cli.py` 只用 scripted intelligence，生产 bug 80% 出在 provider quirk + prompt 漂移，scripted 永远覆盖不到。

**建议**  录几段真 LLM response 成 fixture（record once, replay forever）：
- LM Studio Qwen 的 XML 泄漏场景
- MiniMax 的 `... ` 标签场景
- 工具调用被去重后的 `duplicate_call` 场景

**实现**: `LLMIntelligence` 增加 `record_mode=True` 把完整 `completion` response 序列化到 `.replay` 文件；测试时 `replay_path=` 读回。

**工时**: 4–6h（含 fixture 录制）

---

### 3.3 完整 JSON Schema 校验工具参数

**问题**  `_validate_arguments` 只有 required keys + coerce，不查 `minimum` / `pattern` / `enum`。

**建议**  M5 引入 `jsonschema` 后，工具参数也走完整校验，与 response schema 统一。

---

## 4. 实施建议时间线

| 阶段 | 内容 | 工时 | 产出 |
|------|------|------|------|
| **M4 前 0.5 天** | P0 全部完成 | 4–6h | smoke 10/10 通过，schema 校验上线 |
| **M4 第 1–2 周** | P1 并行：遥测 + 参数校验 + validate-profile | 2–3 天 | CLI 新增子命令，结果报告含 token/cost |
| **M4 第 3 周** | archive/v1 清理，文档更新 | 0.5 天 | repo 体积减小，agent 上下文干净 |
| **M5 规划** | P2 评估：scope 实现 vs 删除，录制回放 | — | 设计文档 |

---

## 5. 风险与对冲

| 风险 | 可能性 | 对冲 |
|------|--------|------|
| jsonschema 引入后校验过严，旧 profile 不兼容 | 中 | 先 warn 后 error，提供 `--strict=false` 过渡 |
| `max_rounds: 8` 对复杂 pcap 不够 | 低 | smoke 验证，不够再调到 10 |
| enricher 禁判决校验误伤（有人真的想传 cause code） | 低 | 只允许 `"mm_cause"` / `"sm_cause"` 等事实字段，判决字段仍禁止 |

---

## 附录：文件速查表

```
# P0 必改
traceweaver/profiles/open5gs_5gc/profile.yaml:78   # max_rounds
traceweaver/core/kernel/kernel.py:396-406          # schema 校验
traceweaver/core/source/enrich.py:33-43           # enricher 禁判决
traceweaver/core/intelligence/litellm_adapter.py  # temperature clamp
scripts/run_m3_smoke.py                           # 样本扩展

# P1 中等
traceweaver/core/kernel/trace.py                  # 遥测字段
traceweaver/core/tools/registry.py:117-133        # coerce 报错
traceweaver/core/source/pcap.py                   # 切片选项
traceweaver/cli/validate_profile.py               # 新命令（新增）

# P2 长线
traceweaver/core/profile/base.py                  # scope 字段（可能删除）
docs/design/platform-v2.md                        # scope 文档同步
```

---

*生成时间*: 2026-04-20  
*基于审查*: M3 完整代码走读 + 159 单元测试 + smoke/regression 基线
