# 已知问题

## 严重

### 1. `_resolved_field_map()` lru_cache 污染测试状态
`traceweaver/tshark/extract.py:96`

进程内永不失效。测试套件里第一次调用的结果会被所有后续测试复用，不同 tshark 环境或 mock 场景下会产生隐藏的测试隔离问题。

### 2. UESession 全量持有原始 records，内存不可控
`traceweaver/models/sessions.py:24`

`records: list[NormalizedRecord]` 和 `frame_numbers: list[int]` 同时存在，前者已包含 frame number，后者冗余。更大的问题是大 PCAP 文件会把所有 NormalizedRecord（含完整 fields dict）全部载入内存，序列化 JSON 时体积爆炸。没有流式处理或懒加载机制。

### 3. 时间窗口关联失败时静默丢弃，无可观测性
`traceweaver/correlate/sbi.py:143`
`traceweaver/correlate/pdu.py:76`
`traceweaver/correlate/ue_sessions.py:76`

三处时间窗口（2s、2s、5s）全部硬编码。关联失败时调用方完全不知道原因，没有 unmatched 计数，没有 warning。在真实故障排查场景里，用户会以为数据不存在，实际上是关联失败了。

---

## 设计问题

### 4. `_parse_optional_int` 三份拷贝
`traceweaver/tshark/extract.py:140`
`traceweaver/correlate/sbi.py:20`
`traceweaver/correlate/pdu.py:11`

完全相同的逻辑，应提取到公共工具模块。

### 5. `correlate_sbi_to_sessions` 有隐式副作用
`traceweaver/correlate/sbi.py:120`

函数返回 `list[SBICall]`，但同时 mutate 了传入的 `sessions`（追加 sbi_calls、更新 suci/supi）。副作用在签名上不可见。

### 6. SMF IP 推断逻辑在多 PDU session 场景下有漏洞
`traceweaver/correlate/pdu.py:57-58`

`infer_smf_ips` 把所有 nsmf-pdusession 调用的目标 IP 合并成一个集合，再赋给该 UE 的所有 PDU flow。若一个 UE 的多个 PDU session 连接到不同 SMF（合法场景），所有 flow 会拿到同一个 IP 集合，导致 PFCP 关联错误。

### 7. Session key 合并逻辑在 RAN ID 复用场景下会合并不同 UE
`traceweaver/correlate/ue_sessions.py:88-94`

当 RAN-UE-NGAP-ID 相同但 AMF-UE-NGAP-ID 不同时，代码将旧 session 的 key 替换。假设了"同一 RAN ID 只对应一个 UE"，在 UE 重新接入导致 RAN ID 复用时，会把两个不同 UE 的记录合并到同一 session。

---

## 工程质量

### 8. CLI `--limit` 语义对用户有误导
`traceweaver/cli.py:66-74`

`extract-sessions`/`extract-sbi`/`extract-pdu-sessions` 的 `--limit` 实际限制的是底层原始 record 数量，而非 session/call 数量。用户传 `--limit 10` 期望得到 10 个 session，实际可能得到 0 个。

### 9. 没有 verbose 模式，调试输出和生产输出混用
`traceweaver/tshark/extract.py:211`

tshark 失败时把完整命令行和 stderr 全部输出，对调试有用但对用户是噪音。没有 `--verbose` 标志，没有 logging 框架。

### 10. `expected_diagnosis.json` 存在但无测试覆盖
`tests/fixtures/expected_diagnosis.json`

定义了 15 个场景的预期诊断结果，但测试套件里没有任何测试使用它。随着代码演进会悄悄过时，目前是死文件。
