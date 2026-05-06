<div align="center">

<pre>
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   ████████╗██████╗  █████╗  ██████╗███████╗██╗    ██╗███████╗  ║
║   ╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██╔════╝██║    ██║██╔════╝  ║
║      ██║   ██████╔╝███████║██║     █████╗  ██║ █╗ ██║█████╗    ║
║      ██║   ██╔══██╗██╔══██║██║     ██╔══╝  ██║███╗██║██╔══╝    ║
║      ██║   ██║  ██║██║  ██║╚██████╗███████╗╚███╔███╔╝███████╗  ║
║      ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚══════╝ ╚══╝╚══╝ ╚══════╝  ║
║                                                               ║
║              <strong>LLM-First Network Diagnostics</strong>              ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
</pre>

<p>
  <a href="#"><img src="https://img.shields.io/badge/Python-3.11+-blue.svg?style=flat-square&logo=python" alt="Python 3.11+"></a>
  <a href="#"><img src="https://img.shields.io/badge/Status-Pre--Alpha-orange.svg?style=flat-square" alt="Status: Pre-Alpha"></a>
  <a href="#"><img src="https://img.shields.io/badge/License-Apache%202.0-green.svg?style=flat-square" alt="License: Apache 2.0"></a>
</p>

<p><strong>English</strong> | <a href="#中文">中文</a></p>

</div>

---

> 🚧 **Development Status** | 开发状态
> 
> **TraceWeaver is in early development (Pre-Alpha).** Core architecture is stabilizing, APIs may change. Not yet suitable for production use. We welcome early adopters and contributors!
> 
> **TraceWeaver 处于早期开发阶段（Pre-Alpha）。** 核心架构正在稳定中，API 可能变动。尚不适合生产环境。欢迎早期采用者和贡献者！

---

## 🎯 Overview | 项目简介

<table>
<tr>
<td width="50%">

**TraceWeaver** is an LLM-first, pluggable platform for network traffic analysis. Upload a PCAP, ask questions in natural language, and receive structured diagnostic reports.

**Key innovation:** Profile-based extensibility. New protocols (5GC, DNS/TCP/TLS/WebSocket, SIP, etc.) require only a profile package—**zero core code changes**.

</td>
<td width="50%">

**TraceWeaver** 是一个基于大语言模型的可插拔网络流量诊断平台。上传 PCAP 文件，用自然语言提问，获得结构化诊断报告。

**核心创新：** 基于 Profile 的扩展性。新增协议（5G核心网、DNS/TCP/TLS/WebSocket、SIP等）只需编写 Profile 包，**无需改动核心代码**。

</td>
</tr>
</table>

---

## ✨ Core Features | 核心特性

| Feature | Description | 特性说明 |
|---------|-------------|----------|
| 🔍 **Zero-Config Parsing** | Auto-detects protocols via tshark | 通过 tshark 自动识别协议 |
| 🧠 **Long-Chain Reasoning** | 6-12 rounds of tool orchestration + LLM inference | 6-12 轮工具编排与 LLM 推理 |
| 🔧 **Tool-First Architecture** | Tools return facts only; LLM makes judgments | 工具只返事实，LLM 独立判断 |
| 🔌 **Pluggable Profiles** | Drop-in protocol support without core changes | 热插拔协议支持，零核心入侵 |
| 🤖 **MCP Integration** | Multi-profile tool surface for external agents (Cursor, Claude, etc.) | 多 Profile 工具暴露，支持外部 Agent 调用 |

---

## 🏗️ Architecture | 架构

```
┌────────────────────────────────────────────────────────────────┐
│                         INPUT                                  │
│                    PCAP / PCAPNG file                          │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│                      PcapSource (tshark)                       │
│              Raw fields ──► Protocol Detection                 │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│                   Profile Enricher                               │
│    frame.protocols ──► DNS_QUERY / TCP_SYN / TLS_CLIENT_HELLO   │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│                    Tool Layer (Read-Only)                        │
│  summarize_capture │ list_flows │ get_timeline │ get_records_... │
│           【Facts Only, No Judgments】                          │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│                     Agent Kernel                                 │
│  Multi-round orchestration (max 12 rounds)                       │
│  Budget management │ Timeout protection │ Schema validation      │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│                       OUTPUT                                     │
│  { summary, failure_layer, root_cause, evidence[],             │
│    remediation, confidence }  ──►  Structured JSON                 │
└────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start | 快速开始

### Installation | 安装

```bash
# Clone repository
git clone https://github.com/your-org/traceweaver.git
cd traceweaver

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Optional: MCP server support
pip install -e ".[mcp-server]"
```

### Basic Usage | 基本用法

```bash
# Analyze a PCAP with default profile
traceweaver analyze \
  --profile web_l4l7_failures \
  --pcap tests/fixtures/web_l4l7/pcaps/03_tcp_rst.pcapng \
  --model openai/qwen/qwen3-14b \
  "Diagnose this network capture. What went wrong?"
```

### MCP Server | MCP 服务

TraceWeaver can expose its diagnostic tools via the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), allowing external agents (Claude Desktop, Cursor, Cline, etc.) to call them directly.

**Start the server** (configure once, use forever):

```bash
# Single profile — capture loaded at runtime via load_capture tool
traceweaver serve --profile open5gs_5gc

# Multi-profile — all profiles available, prefixed tools
traceweaver serve \
  --profile open5gs_5gc \
  --profile web_l4l7_failures \
  --default-profile open5gs_5gc
```

**In the agent**, load captures on demand — no server restart needed:

```
User: 帮我分析一下 /tmp/registration_failure.pcapng
Agent: [calls load_capture(path="/tmp/registration_failure.pcapng")]
       [calls summarize_capture → list_ue_sessions → get_ue_timeline → ...]
       [returns diagnosis]
```

When multiple profiles are loaded, profile-specific tools are **prefixed** with `<profile>__`:

| Tool name | Owner |
|-----------|-------|
| `load_capture` | meta-tool (load a pcap at runtime) |
| `list_profiles` | meta-tool (list loaded profiles) |
| `list_captures` | meta-tool (show loaded captures) |
| `query_records` | built-in (routes to default profile) |
| `search_knowledge` | built-in |
| `open5gs_5gc__summarize_capture` | open5gs_5gc |
| `open5gs_5gc__load_capture` | open5gs_5gc |
| `web_l4l7_failures__list_flows` | web_l4l7_failures |

**Claude Desktop configuration** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "traceweaver": {
      "command": "traceweaver",
      "args": [
        "serve",
        "--profile", "open5gs_5gc",
        "--profile", "web_l4l7_failures",
        "--default-profile", "open5gs_5gc"
      ]
    }
  }
}
```

> No `--pcap` needed in the config. The agent calls `load_capture(path=...)` whenever it has a new file to analyze.

**Replay** — verify a recorded LLM session deterministically:

```bash
traceweaver replay \
  --profile open5gs_5gc \
  --pcap path/to/capture.pcapng \
  --recording path/to/session.yaml
```

---

## 📊 Reference Profiles | 参考实现

| Profile | Scenarios Covered | Status |
|---------|-------------------|--------|
| `open5gs_5gc` | 5G Core: Registration, PDU Session, Deregistration failures | ✅ Stable (9/9 smoke tests) |
| `web_l4l7_failures` | DNS NXDOMAIN, TCP RST, TLS cert expired, WS disconnect | ✅ Stable (4/5 smoke tests) |

---

## 🗺️ Roadmap | 路线图

- [x] **M1-M3**: Core architecture, LLM-first loop, 5GC reference profile
- [ ] **M4**: Third-party profile distribution (entry_points)
- [ ] **M5**: Case Memory / RecordReplayIntelligence
- [ ] **M6**: MCP server / HTTP server for external agent integration
- [ ] **M7**: Multi-source support (external extension)

See [ROADMAP.md](./ROADMAP.md) for detailed planning.

---

## 🤝 Contributing | 贡献

We welcome contributions! Please see our [Contributing Guide](./docs/contributing.md) (coming soon).

欢迎贡献！请查看 [贡献指南](./docs/contributing.md)（即将推出）。

---

## 📄 License | 许可证

Apache License 2.0 - see [LICENSE](./LICENSE) file for details.

根据 Apache 2.0 许可证授权，您可以自由使用、修改和分发本软件，但需保留原始版权和许可证声明。

---

<div align="center">

**Made with ❤️ for network engineers who deserve better tools.**

<em>为值得更好工具的网络工程师而造。</em>

</div>

---

<h2 id="中文">📝 中文补充说明</h2>

### 项目背景

TraceWeaver 诞生于一个朴素的需求：**降低网络抓包分析的门槛**。传统的 Wireshark/tshark 分析需要深厚的协议知识和复杂的过滤语法，一次故障排查往往需要 30-60 分钟。

我们的解决方案是：**让大语言模型成为网络诊断的副驾驶**。用户只需上传抓包文件并用自然语言描述现象，系统自动完成协议解析、语义增强、多轮推理，最终输出结构化的根因分析和修复建议。

### 核心设计原则

1. **工具只返事实，不下判断** —— 强制 LLM 独立完成推理
2. **Core 与 Profile 彻底分离** —— 新协议支持零核心入侵
3. **MCP 协议优先** —— 可被 Cursor、Claude 等外部 Agent 调用

### 快速上手

```bash
# 安装
pip install -e ".[dev,mcp-server]"

# 命令行诊断
traceweaver analyze --profile open5gs_5gc --pcap capture.pcapng "为什么注册失败？"

# 启动 MCP 服务（配一次，反复用）
traceweaver serve --profile open5gs_5gc --profile web_l4l7_failures

# Agent 端调用 load_capture 加载抓包，无需重启服务
```

### Claude Desktop / Cursor 配置示例

```json
{
  "mcpServers": {
    "traceweaver": {
      "command": "traceweaver",
      "args": ["serve", "--profile", "open5gs_5gc", "--profile", "web_l4l7_failures"]
    }
  }
}
```

配好之后，agent 遇到抓包分析需求时直接调 `load_capture(path="/path/to/pcap")`，然后用 `summarize_capture` 等工具诊断，**换抓包不用改配置**。

### 技术栈

- **Python 3.11+** — 类型安全、性能优异
- **Pydantic v2** — 数据验证与序列化
- **LiteLLM** — 统一 LLM 调用接口
- **tshark** — 底层协议解析引擎
- **MCP SDK** — Model Context Protocol 集成

</div>
