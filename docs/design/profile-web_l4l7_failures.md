# Profile 设计：`web_l4l7_failures`

> **目的**：作为 TraceWeaver 的第二个 reference profile，覆盖 web/互联网开发者最常踩的
> **L4-L7 连接级故障**（DNS / TCP / TLS / WebSocket）。同时充当"core 真的协议无关吗？"的硬指标——
> 任何为 5GC profile 私下打的耦合都会在写这个 profile 时暴露出来。
>
> 范围**不含 HTTPS application 层**（5xx / API 重试 / CORS）—— 那需要 SSLKEYLOGFILE 解密，搭环境复杂度
> 翻倍，留到 v0.2。

---

## 1. 边界与不做的事

**做**：

| 子场景 | 故障空间 | 不需解密 |
| --- | --- | --- |
| **DNS** 解析故障 | NXDOMAIN / SERVFAIL / 超时 / 错误 NS | ✅ |
| **TCP** 连接故障 | RST / SYN 无回应 / 端口拒绝 / 半开连接 | ✅ |
| **TLS** 握手故障 | 证书过期 / SNI 不匹配 / cipher 协商失败 / 客户端 alert | ✅（看握手就够，不解密 application） |
| **WebSocket** 异常断连 | close code 异常 / 心跳超时 / Upgrade 失败 | 部分（握手明文，frame 看长度即可） |

**不做**：

- HTTP/2 application 层（GET/POST/5xx）—— 加密包看不到，要 keylog
- HTTP/3 (QUIC) —— 3GPP 范围之外的额外协议栈
- HAR 文件（前端 waterfall）—— 不走 tshark 路径，会撑大 source 抽象
- mTLS / SNI ESNI / DoH —— 边角，先稳住主流故障

理由：**保持 tshark + pcap 单源路径**，与 5GC profile 同构。

---

## 2. 与 5GC profile 的概念映射

| 5GC 概念（已实现） | `web_l4l7_failures` 对应物 |
| --- | --- |
| `RAN_UE_NGAP_ID` / `AMF_UE_NGAP_ID`（UE 会话标识） | `flow_id` = `(stream_id, protocol_layer)` 复合 key |
| `event = REGISTRATION_REQUEST` | `event = TCP_SYN` / `DNS_QUERY` / `TLS_CLIENT_HELLO` / `WS_CLOSE` |
| `5gmm_cause` / `5gsm_cause`（数字 cause） | `dns_rcode` / `tcp_termination_cause` / `tls_alert_code` / `ws_close_code` |
| `protocol_layer = nas_5gmm` | `protocol_layer = dns / tcp / tls / websocket` |
| `ngap.procedureCode`（内部分类） | `tls.handshake.type` / `tcp.flags` |
| `pdu_session_id` | `tcp.stream` 或 `dns.id` |

---

## 3. 事件模型（首版）

事件名以**英文大写下划线**形式跟 5GC 保持一致风格。

### 3.1 DNS

```
DNS_QUERY                 # qclass + qname + qtype
DNS_RESPONSE_OK           # rcode == 0 且至少一条 answer
DNS_RESPONSE_NXDOMAIN     # rcode == 3
DNS_RESPONSE_SERVFAIL     # rcode == 2
DNS_RESPONSE_OTHER        # 其它 rcode
DNS_QUERY_UNANSWERED      # synthetic：query 后 N 秒内无 response
```

### 3.2 TCP

```
TCP_SYN                   # SYN flag set 且无 ACK
TCP_SYN_ACK               # SYN+ACK
TCP_HANDSHAKE_DONE        # synthetic: 三次握手完成的那一帧
TCP_FIN                   # 任一端发 FIN
TCP_RST                   # RST set，附带方向
TCP_CONNECTION_FAILED     # synthetic: SYN 后超时未收到 SYN+ACK
TCP_RETRANSMIT            # tshark 标记的 retransmission（频次 ≥ 3 视为故障）
```

### 3.3 TLS

```
TLS_CLIENT_HELLO          # 含 SNI / cipher_suites
TLS_SERVER_HELLO          # 含 selected cipher
TLS_CERTIFICATE           # 含 subject CN / SAN / not_after
TLS_HANDSHAKE_DONE        # synthetic: Finished 双向完成
TLS_ALERT                 # 含 level (warning/fatal) + description code
TLS_HANDSHAKE_FAILED      # synthetic: Alert fatal 或 早期 RST
```

### 3.4 WebSocket

```
WS_HANDSHAKE_REQUEST      # HTTP Upgrade: websocket
WS_HANDSHAKE_RESPONSE_OK  # 101 Switching Protocols
WS_HANDSHAKE_FAILED       # 非 101 响应
WS_PING / WS_PONG
WS_CLOSE                  # 含 close_code + reason
WS_CONNECTION_DROPPED     # synthetic: TCP 层 RST/FIN 在没收到 WS_CLOSE 时
```

每个事件对应一个 enricher 分支，纯函数，零状态（synthetic 事件需要时间窗口推断的，放在 enricher 的"二次扫描"阶段——参考 5GC `enrich.py` 已有模式）。

---

## 4. 工具集合（首版 6 个，对标 5GC 6 个）

| 名称 | 功能 | 对标 5GC |
| --- | --- | --- |
| `summarize_capture` | 资本盘点：每协议事件计数 + flow 数量 + capture_signals | `summarize_capture` |
| `list_flows` | 列出每个 flow（dns_id / tcp_stream / tls_session）一行汇总 | `list_ue_sessions` |
| `get_flow_timeline(flow_id)` | 单个 flow 的事件时间线 | `get_ue_timeline` |
| `get_dns_queries` | DNS 专题：query → response 配对 + rcode 统计 | `get_sbi_calls` |
| `get_tls_handshakes` | TLS 专题：每握手 SNI / cipher / cert subject / alert | （新） |
| `get_records_around(seq, before, after)` | 通用上下文 | `get_records_around` |

`search_knowledge` 来自 builtin 工具不计入 profile 自带。

---

## 5. profile.yaml 草稿

```yaml
name: web_l4l7_failures
version: "0.1"
display_name: "Web L4-L7 connection failures (DNS / TCP / TLS / WebSocket)"
description: >
  Diagnosis profile for the most common HTTP-stack failures a backend or
  ops engineer hits day-to-day: DNS resolution gone wrong, TCP refused
  or RST'd, TLS handshake failures (cert / SNI / cipher), and abnormal
  WebSocket disconnects. No application-layer decryption — handshake
  observation is enough.

applies_to_sources:
  - pcap

source_config:
  pcap:
    display_filter: "dns || tcp || tls || websocket"
    tshark_options: []
    fields:
      - "frame.protocols"
      - "frame.time_relative"
      - "ip.src"
      - "ip.dst"
      - "ipv6.src"
      - "ipv6.dst"
      - "tcp.srcport"
      - "tcp.dstport"
      - "tcp.stream"
      - "tcp.flags"
      - "tcp.flags.syn"
      - "tcp.flags.ack"
      - "tcp.flags.fin"
      - "tcp.flags.rst"
      - "tcp.analysis.retransmission"
      - "udp.srcport"
      - "udp.dstport"
      - "udp.stream"
      - "dns.id"
      - "dns.flags.response"
      - "dns.flags.rcode"
      - "dns.qry.name"
      - "dns.qry.type"
      - "dns.resp.name"
      - "tls.handshake.type"
      - "tls.handshake.extensions_server_name"
      - "tls.handshake.ciphersuite"
      - "tls.handshake.certificate"
      - "tls.handshake.extensions.supported_version"
      - "tls.alert_message.level"
      - "tls.alert_message.desc"
      - "websocket.opcode"
      - "websocket.payload_length"
      - "http.request.method"
      - "http.request.uri"
      - "http.response.code"
      - "http.upgrade"
    key_strategy:
      mode: "derived_fields"
      fields:
        - "tcp.stream"
        - "dns.id"

enrichers:
  - module: traceweaver.profiles.web_l4l7_failures.enrich
    function: enrich

tools:
  - module: traceweaver.profiles.web_l4l7_failures.tools.summarize_capture
    class: SummarizeCaptureTool
  - module: traceweaver.profiles.web_l4l7_failures.tools.list_flows
    class: ListFlowsTool
  - module: traceweaver.profiles.web_l4l7_failures.tools.get_flow_timeline
    class: GetFlowTimelineTool
  - module: traceweaver.profiles.web_l4l7_failures.tools.get_dns_queries
    class: GetDNSQueriesTool
  - module: traceweaver.profiles.web_l4l7_failures.tools.get_tls_handshakes
    class: GetTLSHandshakesTool
  - module: traceweaver.profiles.web_l4l7_failures.tools.get_records_around
    class: GetRecordsAroundTool

knowledge:
  - file: knowledge/dns_rcodes.md
    tags: ["dns", "rcode"]
  - file: knowledge/tcp_state_machine.md
    tags: ["tcp", "termination"]
  - file: knowledge/tls_alert_codes.md
    tags: ["tls", "alert"]
  - file: knowledge/ws_close_codes.md
    tags: ["websocket", "close"]

llm:
  system_prompt_file: prompts/system.md
  response_schema_file: schema/diagnosis.json
  max_rounds: 8
  recommended_model: "openai/qwen/qwen3.5-9b"
```

---

## 6. 测试环境（docker-compose）

**约束**：用户当前 Windows + 我无 Docker shell，所以**脚本必须由用户运行**。
我交付的脚本必须：

1. 一键 `docker compose up`
2. 全部抓包自动化（在专门的 netshoot sidecar 容器里跑 tshark，pcap 落到 host volume）
3. 一键 `docker compose down` 清理

### 6.1 服务拓扑

```
                     ┌─────────────────────┐
                     │ dnsmasq             │  10.5.0.10
                     │ (custom A records   │
                     │  + 可控 NXDOMAIN)   │
                     └──────────┬──────────┘
                                │
        ┌───────────────────────┼─────────────────────────┐
        │                       │                         │
   ┌────▼──────┐         ┌──────▼──────┐          ┌───────▼────────┐
   │ target    │         │ tls-broken  │          │ ws-flaky       │
   │ nginx     │  443    │ nginx with  │  4443    │ python ws echo │
   │ + valid   │         │ expired /   │          │ + idle kill    │
   │   cert    │         │ SNI mismatch│          │                │
   └───────────┘         └─────────────┘          └────────────────┘

   ┌───────────────────────┐         ┌─────────────────────────────┐
   │ client (curl/wscat)   │         │ injector (busybox+iptables) │
   └───────────────────────┘         └─────────────────────────────┘

                                ┌──────────────┐
                                │  netshoot    │
                                │  tshark -i   │
                                │  → /pcaps    │ ← bind mount to host
                                └──────────────┘
```

### 6.2 5 份 MVP pcap

按"成功 + 4 个典型故障"起步，证明 profile 端到端可跑后再扩：

| pcap | 制造方式 | 期望关键事件 |
| --- | --- | --- |
| `01_web_ok.pcapng` | curl https://server.local/ → 200 | DNS_RESPONSE_OK / TCP_HANDSHAKE_DONE / TLS_HANDSHAKE_DONE |
| `02_dns_nxdomain.pcapng` | curl https://does-not-exist.local/ | DNS_RESPONSE_NXDOMAIN |
| `03_tcp_rst.pcapng` | curl http://server.local:9999/ （injector iptables -j REJECT --reject-with tcp-reset on :9999） | TCP_RST |
| `04_tls_cert_expired.pcapng` | curl https://tls-broken.local:4443/ （nginx 证书 not_after = yesterday） | TLS_ALERT (fatal, certificate_expired) |
| `05_ws_idle_killed.pcapng` | wscat connect → server kill -9 一个 worker | WS_CONNECTION_DROPPED 无 WS_CLOSE |

后续可加：DNS_TIMEOUT / TCP_CONNECTION_FAILED / TLS_SNI_MISMATCH / WS_HANDSHAKE_FAILED 等扩展场景。

### 6.3 目录结构

```
tests/fixtures/web_l4l7/
├── docker-compose.yml
├── README.md                         # 用户怎么跑
├── dnsmasq/
│   └── hosts.conf
├── tls-broken/
│   ├── Dockerfile                    # nginx + 证书生成脚本
│   └── gen_expired_cert.sh
├── ws-flaky/
│   └── server.py                     # asyncio websocket echo + idle kill
├── nginx-target/
│   ├── Dockerfile
│   └── gen_valid_cert.sh
├── scripts/
│   ├── 01_capture_web_ok.sh
│   ├── 02_capture_dns_nxdomain.sh
│   ├── 03_capture_tcp_rst.sh
│   ├── 04_capture_tls_cert_expired.sh
│   ├── 05_capture_ws_idle_killed.sh
│   └── capture_all.ps1               # Windows 入口：docker compose up + 5 个抓包 + down
└── pcaps/
    └── .gitkeep                      # pcap 文件不入 git，路径在 .gitignore 已含 reports/
```

PCAP 入不入 git 是个独立决定：
- **入 git**：reproducibility 最高，新机器 clone 即可跑
- **不入 git**：repo 体积可控（5 份 pcap 大约 100KB-1MB，其实可以入）

**建议入 git**——它们就是单元测试的 fixture，与 5GC 的 `tests/data/*.pcapng` 同性质。

---

## 7. 落地分阶段计划

| 阶段 | 内容 | 时间预估 |
| --- | --- | --- |
| **M6'.0 设计** | 本文件（已完成） | done |
| **M6'.1 docker-compose 骨架** | docker-compose.yml + 4 个服务的 Dockerfile + 抓包脚本 | 0.5 天 |
| **M6'.2 抓 5 份 pcap** | 用户跑 `capture_all.ps1`，pcap 入 `tests/fixtures/web_l4l7/pcaps/` | 用户 30 分钟 |
| **M6'.3 enrich.py + fields.py** | 拿到真实 pcap 后写解析层，跑 `tshark -T fields` 校验字段都拿得到 | 0.5 天 |
| **M6'.4 6 个工具实现** | summarize / list_flows / get_flow_timeline / get_dns_queries / get_tls_handshakes / get_records_around | 1 天 |
| **M6'.5 system.md + 4 份 knowledge** | DNS rcode / TCP 状态 / TLS alert / WS close codes | 0.5 天 |
| **M6'.6 测试** | 6 个工具单测 + 1 个 e2e（用 fixture pcap 跑 `analyze`，比 5GC 还简化） | 0.5 天 |
| **总计** | | 3-4 天 |

**重要顺序约束**：M6'.3-.6 必须在 M6'.2 完成后才能开始——必须用真 pcap 做 schema 推断。

---

## 8. 需要用户在 M6'.1 之前确认

1. **Docker 是否可用**？Windows 上推荐 Docker Desktop（WSL2 后端）。我能写 docker-compose.yml 但跑得起来要靠你。
2. **PCAP 入 git** 是否同意？（建议入；独立决定）
3. **是否同意上面"5 份 MVP pcap"的范围**？范围决定接下来 docker-compose 服务编排。
4. **profile 名 `web_l4l7_failures`** 是否 OK？太长可改 `web_failures` 或 `http_l4l7`，但语义明确度会降。

---

## 9. 与 §1 北极星硬指标的映射

按 ROADMAP §1：

> "加入一种新协议（任意 vendor 5GC、4G EPC、SIP/VoIP、SDN 控制面、应用层…）只需写一份 profile 包，**不改 core**。"

执行本设计时如果发现以下任一情况发生，意味着**core 还没真正协议无关**：

- enricher 被迫导入任何 `traceweaver.profiles.open5gs_5gc.*` 模块
- ToolSpec / SourceSpec / Record 不能直接复用，要去 core 改字段
- key_strategy 模式不够用（5GC 用 derived_fields，web 也用，但万一不够）
- prompt 渲染管线对 5GC 字段名硬编码（如某处假设 `mm_cause` 字段一定存在）

每发现一处，记录到 `docs/improvements/` 一个新的 `m6-core-coupling-<n>.md`，**先在 web profile 里 work-around**，**M7' 阶段统一上提到 core**——避免 web profile 节奏被 core 重构拖死。

---

写到此处已经覆盖足够的设计细节让 M6'.1 立刻可以动手。等用户对 §8 的 4 个问题给出反馈后，下一步即是：

```
1. 创建 tests/fixtures/web_l4l7/docker-compose.yml + 服务配置
2. 创建 5 个 capture 脚本
3. 写一个 README.md 让用户能 5 分钟内跑完抓包
4. 等待用户提交 5 份 pcap
```
