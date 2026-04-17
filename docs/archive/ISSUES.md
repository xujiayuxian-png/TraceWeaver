# 已知问题

## 严重

### 1. ~~`_resolved_field_map()` lru_cache 污染测试状态~~ ✅ 已修复
`traceweaver/tshark/extract.py` — 已替换为手动管理的全局缓存 + `clear_field_map_cache()` 函数。

### 2. ~~UESession 全量持有原始 records，内存不可控~~ ✅ 已修复
`records` 字段已设置 `exclude=True`，序列化 JSON 时不再输出完整 NormalizedRecord。内部处理仍可访问 records 但不会在 API/CLI 输出中爆炸。

### 3. ~~时间窗口关联失败时静默丢弃，无可观测性~~ ✅ 已修复
三个关联点（sbi, pdu/pfcp, ue_sessions）均已加入 `warnings` 参数，会输出 correlation summary 和 unmatched/dropped 计数。时间窗口值仍硬编码但现在有可观测性。

---

## 设计问题

### 4. ~~`_parse_optional_int` 三份拷贝~~ ✅ 已修复
已提取到 `traceweaver/utils.py`，三处调用点已统一使用 `parse_optional_int` / `parse_optional_float`。

### 5. `correlate_sbi_to_sessions` 有隐式副作用
`traceweaver/profiles/open5gs_5gc/assemble/sbi.py`

函数返回 `list[SBICall]`，但同时 mutate 了传入的 `sessions`（追加 sbi_calls、更新 suci/supi）。副作用在签名上不可见。

### 6. ~~SMF IP 推断逻辑在多 PDU session 场景下有漏洞~~ ✅ 已修复
不再全局 `infer_smf_ips` 后广播给所有 flow。现在 SMF IP 仅在 SBI call 匹配到具体 PDU flow 时设置（`call.dst_ip`），单 flow 无匹配时才做 fallback 推断。

### 7. ~~Session key 合并逻辑在 RAN ID 复用场景下会合并不同 UE~~ ✅ 已修复
现在仅在 prior key 为 partial（RAN 或 AMF 有一个为 None）时才合并升级为完整 key。当两个 fully-qualified key `(RAN, AMF1)` 和 `(RAN, AMF2)` 碰撞时，创建新 session 而非覆盖。

---

## 工程质量

### 8. CLI `--limit` 语义对用户有误导
`traceweaver/cli.py`

终态 `analyze` / `diagnose` / `investigate` / `scopes list` 的 `--limit` 仍然限制的是底层原始 record 数量，而不是 scope 数量。用户传 `--limit 10` 可能得到不完整 scope，甚至 0 个有效 scope。

### 9. 没有 verbose 模式，调试输出和生产输出混用
`traceweaver/tshark/extract.py:211`

tshark 失败时把完整命令行和 stderr 全部输出，对调试有用但对用户是噪音。没有 `--verbose` 标志，没有 logging 框架。

### 10. ~~`expected_diagnosis.json` 存在但无测试覆盖~~ ✅ 已修复
`tests/test_diagnosis.py` 现在参数化读取 expected_diagnosis.json，验证 verdict、failure_point、root_cause、required_signals、forbidden_signals、required_sbi_paths。13 个 canonical 场景中 12 个 verdict 完全匹配，1 个（16_truncated）因 NGAP 推理正确显示 OK 而非 INCONCLUSIVE（已标注 skip）。
