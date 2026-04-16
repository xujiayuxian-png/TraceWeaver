# TraceWeaver 终态重构施工方案

## 1. 目标

本次重构采用一次性终态切换，不保留兼容层，不维护双轨结构。

重构后必须达成：

- `core` 只承载平台能力与公共 contract
- `profiles/open5gs_5gc` 成为唯一 5GC / Open5GS 语义承载层
- `traceweaver/models` 不再作为公共模型层使用
- `traceweaver/tshark` 不再承载 5GC 专属抽取逻辑
- `core/contracts` 成为 agent / report / orchestration 的唯一公共 contract

## 2. 当前问题归纳

### 2.1 顶层 `models` 目录语义错误

`traceweaver/models` 中当前包含：

- `UESession`
- `PDUSessionFlow`
- `PFCPFlow`
- `SBICall`
- `NormalizedRecord`
- `ExtractedRecordSet`

这些都不是平台公共模型，而是 5GC 域模型。

### 2.2 顶层 `tshark` 混合了平台能力和 5GC 专属逻辑

- `tools.py` 基本是平台通用能力
- `extract.py` 则内嵌：
  - `DEFAULT_5GC_DISPLAY_FILTER`
  - `DEFAULT_5GC_DECODE_AS`
  - `FIELD_SPECS`
  - `extract_5gc_records()`

这导致平台边界被 5GC 语义污染。

### 2.3 主数据流仍由 legacy 5GC model 主导

当前权威数据流仍然是：

- `ExtractedRecordSet`
- `UESession`
- `PDUSessionFlow`
- `SessionDiagnosis`

`core/contracts` 目前更多是在做统一输出投影，而非真正接管主生命周期。

## 3. 终态目录

```text
traceweaver/
  core/
    analysis/
      engine.py
      options.py
      result.py
    contracts/
      record.py
      event.py
      scope.py
      signal.py
      evidence.py
      diagnosis.py
      visibility.py
    profile/
      base.py
      registry.py
    tshark/
      runner.py
      fields.py
      packet_access.py
    agent/
      engine.py
      planner.py
      result.py
      tools.py
    llm/
      provider.py
      output.py
      prompts.py
    capture.py

  profiles/
    open5gs_5gc/
      __init__.py
      profile.py
      defaults.py
      fields.py
      domain/
        __init__.py
        records.py
        events.py
        sbi.py
        pdu.py
        sessions.py
        diagnosis.py
        capture.py
      extract/
        records.py
      events/
        identify.py
      assemble/
        ue.py
        sbi.py
        pdu.py
      diagnosis/
        engine.py
        llm_engine.py
        signals.py
      investigation/
        registry.py
        tools.py
      report/
        markdown.py
      knowledge/

  cli.py
  __init__.py
```

## 4. 文件迁移表

### 4.1 顶层 `models` 下沉

- `traceweaver/models/records.py`
  - -> `traceweaver/profiles/open5gs_5gc/domain/records.py`

- `traceweaver/models/events.py`
  - -> `traceweaver/profiles/open5gs_5gc/domain/events.py`

- `traceweaver/models/sbi.py`
  - -> `traceweaver/profiles/open5gs_5gc/domain/sbi.py`

- `traceweaver/models/pdu.py`
  - -> `traceweaver/profiles/open5gs_5gc/domain/pdu.py`

- `traceweaver/models/sessions.py`
  - -> `traceweaver/profiles/open5gs_5gc/domain/sessions.py`

- `traceweaver/models/diagnosis.py`
  - -> `traceweaver/profiles/open5gs_5gc/domain/diagnosis.py`

- `traceweaver/models/capture.py`
  - -> `traceweaver/profiles/open5gs_5gc/domain/capture.py`

### 4.2 顶层 `tshark` 拆分

- `traceweaver/tshark/tools.py`
  - 平台通用部分 -> `traceweaver/core/tshark/runner.py`

- `traceweaver/tshark/extract.py`
  - 通用字段/命令执行部分 -> `traceweaver/core/tshark/fields.py` / `packet_access.py`
  - 5GC 专属字段、默认过滤器、5GC 抽取器 -> `traceweaver/profiles/open5gs_5gc/fields.py` / `defaults.py` / `extract/records.py`

## 5. 接口重写要求

### 5.1 `AnalysisProfile` 重写

当前 `AnalysisProfile` 接口过粗。终态需要拆成：

- `extract()`
- `build_scopes()`
- `annotate_signals()`
- `assess_visibility()`
- `collect_evidence()`
- `diagnose_scope()`
- `build_investigation_tool_registry()`

### 5.2 `core.analysis.engine` 接管主流程

`core.analysis.engine` 负责 orchestrate：

- 调用 profile 抽取 runtime
- 调用 profile 产出 scopes
- 对每个 scope 调用 signals / visibility / evidence / diagnosis
- 最终统一组装 `AnalysisResult`

### 5.3 `profile.py` 从厚 orchestrator 降为 hook provider

`profiles/open5gs_5gc/profile.py` 不再内部串联完整 legacy pipeline，而是只负责提供 profile 生命周期实现。

## 6. 施工顺序

### 阶段一：域模型下沉

目标：让 5GC 运行态模型全部进入 `profiles/open5gs_5gc/domain/`。

动作：

- 新建 `domain/` 目录与模型文件
- 批量修改 `profiles/open5gs_5gc/*`、`traceweaver/llm/prompts.py`、测试文件中的 import
- 停止任何新代码继续依赖 `traceweaver.models`

### 阶段二：拆分 `tshark`

目标：把 5GC 专属抽取能力从平台层剥离。

动作：

- 新建 `core/tshark/`
- 迁移通用 runner / field access
- 在 `profiles/open5gs_5gc` 内建立 `defaults.py`、`fields.py`、`extract/records.py`
- 让 5GC profile 只依赖新的 profile-local extract

### 阶段三：重写 profile lifecycle

目标：让 `core.analysis.engine` 成为唯一权威 orchestrator。

动作：

- 重写 `AnalysisProfile`
- 重构 `Open5GS5GCProfile`
- 删除 `profile.analyze_capture()` 风格的厚入口

### 阶段四：清理旧层

目标：移除 dead code 和误导性导出。

动作：

- 删除顶层 `traceweaver/models`
- 删除顶层 `traceweaver/tshark/extract.py` 与相关 5GC 导出
- 清理所有旧 import

## 7. 硬验收标准

### 7.1 结构验收

- `core/` 中不得再出现 `UE`、`PDU`、`AMF`、`SMF`、`NGAP`、`PFCP`、`SBI`、`Open5GS`
- `profiles/open5gs_5gc` 成为唯一 5GC 语义承载层

### 7.2 依赖验收

- `core/*` 不 import `traceweaver.models`
- `core/*` 不 import `profiles/open5gs_5gc/domain/*`
- `traceweaver/llm/prompts.py` 不再依赖 legacy 顶层 model 路径

### 7.3 运行验收

以下命令通过：

- `traceweaver profiles list`
- `traceweaver scopes list ...`
- `traceweaver analyze ...`
- `traceweaver diagnose ...`
- `traceweaver investigate ...`

### 7.4 测试验收

- 现有关键测试通过
- 新增至少一组“平台边界测试”

## 8. 实施策略说明

虽然这是一次性终态重构，但在同一条分支里仍按阶段推进，以保证每一步都可验证。

原则：

- 不新增兼容 wrapper
- 不保留旧导出给新代码继续使用
- 每完成一阶段就立即修 import 和跑测试
