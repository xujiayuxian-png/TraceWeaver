# Ollama qwen3.5:9b 全量批测与对齐分析

## 测试背景

目标是在 Windows 本机环境下，验证 TraceWeaver 使用 `Ollama + qwen3.5:9b` 做 5GC 诊断的可行性、稳定性与对齐质量。

本轮测试基于以下前提：

- 已修复 Windows 下 `tshark` / `capinfos` 输出的 UTF-8 解码问题
- 已修复 `ollama/qwen3*` 在 OpenAI 兼容接口下默认 thinking 模式导致 `message.content` 为空的问题
- 当前 LLM 调用链通过 `litellm` 统一接入，并默认对 `ollama/qwen3*` 注入 `extra_body={"think": false}`

## 测试配置

- 模型：`ollama/qwen3.5:9b`
- API Base：`http://127.0.0.1:11434`
- 样本目录：`tests/fixtures/pcap`
- 批测时间：`2026-04-16`

## 全量运行结果

- 总样本数：`28`
- 成功完成诊断流程：`28`
- 运行错误：`0`
- `llm_fallback` 次数：`0`
- 总耗时：约 `476.323s`

这说明从工程链路角度看：

- Windows 本机环境可稳定跑通
- `Ollama + qwen3.5:9b` 已经可以稳定参与诊断
- 当前修复足以避免因空 `content` 导致的 JSON 解析失败和回退到规则引擎

## 与基线的对齐范围

可直接与 `tests/fixtures/expected_diagnosis.json` 对齐的样本共有 `16` 个：

- `canonical`：`13`
- `usable_with_note`：`2`
- `candidate_only`：`1`

其余 `12` 个样本这次只做运行验证，不做严格评分。

## 对齐指标

### 全部有基线的 16 个样本

- `verdict` 命中：`14/16` = `87.5%`
- `failure_point` 命中：`10/16` = `62.5%`
- `root_cause` 精确命中：`6/16` = `37.5%`
- `confidence` 命中：`11/16` = `68.8%`

### canonical 的 13 个正式样本

- `verdict` 命中：`11/13` = `84.6%`
- `failure_point` 命中：`8/13` = `61.5%`
- `root_cause` 精确命中：`6/13` = `46.2%`
- `confidence` 命中：`11/13` = `84.6%`

## 结果解读

不能只看 `root_cause` 精确命中率，因为这里混合了三类完全不同的情况：

- 标签命名不一致
- 自然语言解释与基线枚举词表不一致
- 真正的诊断判断错误

当前大部分失配属于前两类，而不是事实判断完全错误。

## 对齐较好的样本类型

- 成功注册样本
- PFCP / UPF 问题导致的 PDU Session 建立失败
- SBI / 鉴权链路出现明显异常的失败样本
- 明确的鉴权失败样本

这些场景下，模型通常能给出方向正确、证据充分的结论。

## 主要失配类型

### 1. 标签体系不完全对齐

典型样本：

- `03_registration_reject.pcapng`
- `04_authentication_failure.pcapng`
- `07_pfcp_failure.pcapng`
- `08_sbi_failure.pcapng`
- `11_registration_retry.pcapng`

问题模式：

- LLM 输出 `Authentication`，而基线要求 `AUTHENTICATION`
- LLM 输出自然语言根因，而基线要求固定枚举，例如 `upf_or_pfcp_downstream_unavailable`
- LLM 能判断“第一次失败后重试成功”，但没有完全命中项目内部的更细粒度标签名

这类问题本质上是“语义对、taxonomy 不完全贴齐”。

### 2. confidence 偏乐观

典型样本：

- `09_multi_ue_concurrent.pcapng`
- `10_deregistration.pcapng`

问题模式：

- 预期是 `medium`
- LLM 给出了 `high`

这更像 calibration 问题，而不是诊断方向错误。

### 3. 证据不完整场景的真正危险失配

典型样本：

- `15_partial_visibility_multi_host.pcapng`
- `16_truncated_or_lossy_capture.pcapng`

问题模式：

- 基线预期：`INCONCLUSIVE`
- LLM 实际输出：`OK`

这说明当前 one-shot 方案有一个重要短板：

- 它更擅长解释“已看到的证据”
- 但不够擅长承认“没看到足够证据”

这也是后续最值得优先修复的点。

## 工程结论

### 已经成立的结论

- 当前链路稳定可用
- `Ollama + qwen3.5:9b` 在本项目里已经具备实用价值
- 普通成功/失败样本上，诊断方向多数正确

### 还不能过度乐观的地方

- 还不能把当前 one-shot LLM 方案当作“完全可靠的自动评测器”
- 对 `partial capture` / `truncated capture` / 证据缺失场景仍存在高风险误判

## 最短改进路线

建议按这个优先级推进：

### 1. 先修 `INCONCLUSIVE` 判定

目标：

- 只要识别到抓包范围不完整、关键层不可见、时间窗口被截断
- 就优先输出 `INCONCLUSIVE`
- 明确说明 `not_captured` / `ambiguous` / `limitations`

### 2. 再做标签归一化

把模型自由文本输出映射到项目基线词表，例如：

- `Authentication` -> `AUTHENTICATION`
- `Registration` -> `REGISTRATION`
- 自然语言 PFCP 故障 -> `upf_or_pfcp_downstream_unavailable`

### 3. 最后做 confidence 校准

在多 UE、去注册、部分可见、时间窗口不足等场景下，把过于乐观的 `high` 收敛到 `medium`

## 附注

本次批测的本地原始结果曾输出到：

- `.traceweaver/llm_batch_qwen3.5_9b_20260416.json`

该文件是本地分析工件；本报告是适合提交到 git 的摘要版本。
