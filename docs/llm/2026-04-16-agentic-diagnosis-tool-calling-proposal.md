# 从 One-Shot 诊断升级到 Agentic Diagnosis 的方案思考

## 背景

当前 TraceWeaver 的 LLM 诊断路径本质上是：

- 先用 `tshark` 和现有相关逻辑抽取结构化事实
- 再把这些事实一次性喂给 LLM
- 让 LLM 做一次 one-shot 诊断输出

这种模式在简单问题上很有效，但在复杂问题上上限明显：

- 如果预先抽取的证据刚好够用，模型能给出不错的判断
- 如果关键证据没有被提前抽出来，模型没有继续追问、补充取证的能力
- 它更像“基于现有摘要做解释”，而不是“像工程师一样逐步定位问题”

## 为什么用户会觉得“这不像特别智能”

因为资深工程师做定位时的工作流不是单次回答，而是：

- 提出一个当前假设
- 明确还缺哪些证据
- 去查更多信息
- 根据新证据修正假设
- 最后再下结论

而现在的 one-shot LLM 诊断，缺少的正是这套“迭代取证”的能力。

## 能不能把 `tshark` 处理 `pcap` 的能力作为 tool 开放给模型

可以，但不建议一开始就把“任意原始 `tshark` 命令”直接裸开放给模型。

### 直接裸开放 `tshark` 的问题

#### 1. 输出量容易失控

`pcap` 数据量很大，模型如果自由查询：

- 容易返回过多帧
- token 成本高
- 结果更乱，不一定更有帮助

#### 2. 查询方式脆弱

原始 `tshark` 依赖：

- 字段名是否正确
- `display_filter` 是否正确
- `decode-as` 是否配置正确
- 不同协议层字段是否可见

这些细节很容易让模型“查不到”或“查歪”。

#### 3. 难以限制探索成本

如果没有 guardrail，模型可能会：

- 连续查很多轮
- 重复查询已有信息
- 为了一个结论付出不成比例的计算与 token 成本

#### 4. 难以审计

如果模型直接拼装任意 `tshark` 调用，后续很难清晰回答：

- 它到底依据哪些查询得出结论
- 哪一步查询是关键证据
- 这条链路是否可复现、可调试

## 更合理的方向：分层工具化，而不是裸 shell 化

### 第一层：高层诊断工具

先把最稳定、最有诊断价值的能力封装成语义化工具，而不是把原始 `tshark` 暴露给模型。

建议的第一批高层工具：

- `get_sessions(pcap)`
  - 列出 UE sessions、标识、时间范围、事件计数

- `get_session_context(pcap, session_id)`
  - 返回该 session 的 timeline、signals、warnings、SBI/PDU 摘要

- `get_sbi_calls(pcap, session_id, service=None, path_contains=None, status=None)`
  - 按 session 和条件过滤 SBI 请求/响应

- `get_pfcp_messages(pcap, session_id, pdu_session_id=None, seid=None)`
  - 查询与 PDU Session 相关的 PFCP 交互

- `get_frames_around(pcap, frame_number, before=5, after=5)`
  - 查看某个关键帧前后的上下文

- `get_capture_visibility(pcap)`
  - 判断是否 partial capture、是否 truncated、是否缺 PFCP、是否缺 HTTP2 decode 等

这层的优点：

- 输出结构化
- token 可控
- 结果更稳定
- 易于审计和复现

### 第二层：参数化的半底层查询工具

当高层工具不够时，再给模型更细粒度的受控查询，而不是直接 shell。

例如：

- `query_frames(pcap, display_filter, fields, limit)`
- `query_http2_calls(pcap, path_contains=None, status=None, limit=50)`
- `query_nas_events(pcap, ran_ue_id=None, amf_ue_id=None, around_frame=None)`
- `query_pfcp_by_seid(pcap, seid, limit=50)`

这里依然是受控 API，而不是让模型自己拼装自由命令。

### 第三层：低频 raw tshark escape hatch

只有在前两层不够时，才考虑提供一个高度受限的 raw 查询接口，例如：

- `run_tshark_query(spec)`

但必须有严格限制：

- 限制允许的字段集合
- 限制最大返回行数
- 限制 `decode-as` 白名单
- 限制只能操作指定 `pcap`
- 自动记录调用日志，确保可审计

## 真正关键的不只是 tool，而是 agent loop

仅仅“加一个 tool”还不够。

真正让系统从“会回答”变成“会定位”的，是让模型进入一个可控的迭代流程：

- 初步判断
- 识别证据缺口
- 主动调用工具补证据
- 更新假设
- 最终输出结论

## 建议的 agent 工作流

### Step 1：给模型现有摘要

先给它：

- session timeline
- signals
- SBI / PFCP 摘要
- warnings
- capture visibility 信息

### Step 2：模型先输出“当前假设 + 还缺什么证据”

例如：

- 当前怀疑是下游 SBI 鉴权链路问题
- 但还需要确认：
  - 是否真的有 `404/5xx/no response`
  - 是否只是 `decode-as` 缺失
  - 是否存在 retry 后恢复

### Step 3：模型自行调用工具

例如：

- `get_capture_visibility`
- `get_sbi_calls`
- `get_frames_around`
- `get_pfcp_messages`

### Step 4：模型更新诊断结论

最后再输出：

- `verdict`
- `failure_point`
- `root_cause`
- `confidence`
- `evidence`
- `limitations`
- `investigation_trace`

这时模型才真正具备“调查式诊断”的特征。

## 对 TraceWeaver 的推荐落地路径

### 方案 A：保守增强版

保留当前 one-shot 链路，只在复杂场景进入 agent 调查。

建议触发条件：

- `INCONCLUSIVE`
- `confidence=low`
- 存在明显 visibility warning
- `multi_ue` / `retry` / `partial_capture` / `truncated_capture`
- 当前输出与规则诊断冲突较大

优点：

- 改动最小
- 风险可控
- 对现有 CLI 和逻辑侵入较小

这是最现实、最值得先做的第一步。

### 方案 B：完整 agent 诊断引擎

把 `llm_diagnose_session()` 升级成真正的多轮 agent：

- 最多 `3-6` 轮
- 每轮可调用有限数量工具
- 每轮更新假设和调查计划
- 最终输出标准化 JSON

优点：

- 能力上限更高
- 更接近真正的“复杂问题定位助手”

缺点：

- 工程复杂度明显更高
- 调试成本和评测成本都会上涨

### 方案 C：双层模型策略

- 小模型做快速初判
- agent 模式只在复杂样本上触发

优点：

- 成本更可控
- 大多数简单样本仍可快速返回
- 把复杂推理预算集中在高价值难样本上

## 为什么最优先应该服务 `INCONCLUSIVE`

从已有全量测试结果看，当前最危险的误判，不是普通故障识别，而是：

- `15_partial_visibility_multi_host`
- `16_truncated_or_lossy_capture`

这类样本真正需要的能力不是“更会解释已知故障”，而是：

- 能主动判断抓包是否完整
- 能承认自己证据不足
- 能把最终结论收敛到 `INCONCLUSIVE`

因此，tool calling 最先应服务的不是更复杂的失败分类，而是：

- `visibility`
- `capture completeness`
- `evidence sufficiency`

## 设计 guardrail 的建议

每次工具调用前，要求模型先说明：

- 当前假设是什么
- 为什么需要调用这个工具
- 这个工具会验证什么

例如：

- 当前怀疑 `AUSF -> UDM` 下游失败
- 需要确认是否存在 `404/5xx/no response`
- 因此调用 `get_sbi_calls(session_id=..., service='nausf-auth')`

这样有两个好处：

- 更便于审计模型的定位思路
- 也能减少模型乱查和重复查询

## 推荐的最小原型范围

如果要先做 MVP，我建议只支持以下三个工具：

- `get_session_context`
- `get_sbi_calls`
- `get_capture_visibility`

然后只在这类样本上试点：

- `partial capture`
- `truncated capture`
- `sbi_failure`

因为这是最容易体现增益、同时风险最低的切入点。

## 结论

### 应该做吗

应该做。

当前 one-shot LLM 诊断已经证明“模型能参与诊断”，但还没有达到“能主动定位复杂问题”的水平。要跨过这一步，tool calling / agentic diagnosis 基本是必经之路。

### 应该怎么做

建议路线是：

- 不要一开始裸开放原始 `tshark`
- 先做高层诊断工具
- 先做受控的 agent loop
- 优先解决 `partial` / `truncated` / `INCONCLUSIVE` 场景
- 必要时再增加低层 raw 查询能力

### 当前最值得优先做的事情

不是让模型“查更多”，而是先让模型学会：

- 何时应该继续取证
- 何时应该承认证据不足
- 何时应该输出 `INCONCLUSIVE`
