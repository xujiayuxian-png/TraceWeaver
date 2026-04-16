# LLM Diagnostics Notes

这组文档整理了 2026-04-16 在 Windows 环境下，用本机 `Ollama + qwen3.5:9b` 对 TraceWeaver 做诊断测试、对齐分析，以及后续 agent/tool-calling 设计讨论的结果。

## 文档清单

- `2026-04-16-ollama-qwen3.5-9b-batch-report.md`
  - 全量 `pcap` 批测结果与对齐分析摘要

- `2026-04-16-ollama-qwen3.5-9b-io-demo-04-authentication-failure.md`
  - 单样本真实 LLM 输入输出示例

- `2026-04-16-agentic-diagnosis-tool-calling-proposal.md`
  - 关于把 `tshark` / 诊断能力 tool 化，并升级为 agentic diagnosis 的方案思考

## 结论速览

- Windows 下 `tshark` 输出编码问题已经修复
- `ollama/qwen3.5:9b` 由于 OpenAI 兼容接口在默认 thinking 模式下可能返回空 `content`，已通过默认注入 `extra_body={"think": false}` 修复
- 全量 `28` 个 `pcap` 已成功跑通，`0 error`、`0 llm_fallback`
- 当前 LLM 方案对普通成功/失败样本已经可用，但对 `partial capture` / `truncated capture` 这类证据不完整场景仍有误判风险
- 后续建议从 one-shot 诊断升级为“受控 tool calling + 迭代取证”的 agentic diagnosis
