# 接入 MCP 客户端：在 Claude Desktop / Cursor / Cline 中使用 TraceWeaver

`traceweaver serve` 把一个 profile 的工具集合通过 [Model Context Protocol](https://modelcontextprotocol.io/)
暴露给外部 agent。本文以 Open5GS 5GC profile + stdio transport 为例，给出
**最小可复现的接入步骤** 和常见问题排查。

> 适用版本：M4' MVP（stdio only）。SSE / HTTP transport 在路线图中，未实现。

## 0. 前置条件

| 项 | 要求 |
| --- | --- |
| Python | ≥ 3.11，安装在 venv，仓库内 `pip install -e .` 完成 |
| tshark | 安装并加入 PATH（Windows 下 Wireshark 默认装在 `C:\Program Files\Wireshark\`） |
| MCP 客户端 | Claude Desktop / Cursor / Cline 任一，且已知配置文件路径 |
| pcap | 一份 5GC NGAP+NAS 抓包，路径会写进 MCP 配置 |

确认 `traceweaver` 命令在 venv 中可用：

```powershell
.venv\Scripts\traceweaver --help
.venv\Scripts\traceweaver serve --help
```

确认 tshark 路径：

```powershell
where.exe tshark
```

应输出 `C:\Program Files\Wireshark\tshark.exe`（或同等路径）。如果没有，请把
Wireshark 安装目录加进系统 PATH，或在下面 MCP 配置里通过 `env` 注入。

## 1. 验证 stdio 传输能跑通

先用仓库自带的 smoke 脚本，确认本机 stdio 通道、profile 加载、tshark 解析全
链路 OK，**再** 去配置 MCP 客户端：

```powershell
.venv\Scripts\python scripts\smoke_mcp_serve.py `
    --profile open5gs_5gc `
    --pcap tests\fixtures\pcap\01_registration_success.pcapng
```

成功输出大致是：

```
[smoke] initialized: server=traceweaver protocol=2025-06-18
[smoke] tools/list returned 9 tools:
          - get_pfcp_exchanges
          - get_sbi_calls
          - get_ue_timeline
          - inspect_record
          - knowledge_lookup
          - list_ue_sessions
          - search_records
          - summarize_capture
          - upf_topology_overview
[smoke] calling summarize_capture ...
[smoke] summarize_capture -> 1 UE(s), 8 total events across event_inventory
[smoke] OK
```

如果这一步失败，**先解决这一步**，外部 MCP 客户端不会比 smoke 脚本更聪明。

## 2. Claude Desktop 配置

Windows 下配置文件路径：`%APPDATA%\Claude\claude_desktop_config.json`

最小可工作配置（注意每段反斜杠在 JSON 中要写成 `\\`）：

```json
{
  "mcpServers": {
    "traceweaver-5gc-reg-success": {
      "command": "D:\\code\\TraceWeaver\\.venv\\Scripts\\traceweaver.exe",
      "args": [
        "serve",
        "--profile", "open5gs_5gc",
        "--pcap",    "D:\\code\\TraceWeaver\\tests\\fixtures\\pcap\\01_registration_success.pcapng"
      ],
      "env": {
        "PATH": "C:\\Program Files\\Wireshark;${PATH}"
      }
    }
  }
}
```

要点：

- `command` 用 venv 中的 `traceweaver.exe` 绝对路径，不要依赖系统 PATH
- pcap 路径必须**绝对路径**，且双反斜杠
- `env.PATH` 仅在 tshark 不在系统 PATH 时需要；用 `${PATH}` 保留原 PATH
- 一份配置 = 一个 capture（M4' MVP 设计：capture 在 server 启动时绑定）。要分析另一份 pcap，再加一个 `mcpServers` entry，名字不要冲突

保存后**完全重启 Claude Desktop**（菜单 → Quit，确认进程退出后再启动）。
重启后在 Claude 对话框右下角应能看到工具图标，点开能列出 9 个工具：
`summarize_capture`、`get_ue_timeline`、`get_pfcp_exchanges`、`get_sbi_calls`、
`list_ue_sessions`、`upf_topology_overview`、`inspect_record`、`search_records`、
`knowledge_lookup`。

试一句话：

> 用 traceweaver-5gc-reg-success 这套工具，先调 summarize_capture，看看这份抓包是什么场景。

## 3. Cursor / Cline 配置

二者的 MCP 配置 schema 与 Claude Desktop 完全一致（都是底层 `mcp` Python SDK
的 stdio transport），把上面的 JSON 段照抄进各自的 MCP 配置文件即可。具体文件路径：

- **Cursor**：设置 → Features → MCP，或编辑 `~/.cursor/mcp.json`
- **Cline**：VS Code 命令面板 → "Cline: Open MCP Settings"

## 4. 多份 pcap 同时挂载

每个 capture 一个 server entry，名字按业务区分：

```json
{
  "mcpServers": {
    "tw-reg-success":  { "command": "...", "args": ["serve","--profile","open5gs_5gc","--pcap","...\\01_registration_success.pcapng"] },
    "tw-pfcp-failure": { "command": "...", "args": ["serve","--profile","open5gs_5gc","--pcap","...\\07_pfcp_failure.pcapng"] }
  }
}
```

LLM 在对话中按 server 名挑选；同时挂多个 server 不会互相串扰。

## 5. 错误排查

### 5.1 客户端启动后看不到工具

1. 在客户端的 MCP 日志里找 `traceweaver` 这一段（Claude Desktop：`%APPDATA%\Claude\logs\mcp*.log`）
2. 大概率是 `tshark not found` 或 pcap 路径错误
3. 用 smoke 脚本（§1）再跑一次，作为对照：smoke 通过、客户端不通过 ⇒ 100% 是配置问题

### 5.2 stderr 里看到 banner，但 stdout 上没数据

正常。`traceweaver serve` 会向 **stderr** 打印一行：

```
[traceweaver-serve] profile=open5gs_5gc tools=9 transport=stdio
```

stdout 全部用作 MCP 协议通道，绝不能出现散逸字节，否则客户端会断开连接。

### 5.3 PowerShell 跑 smoke 退出码 1，但实际 OK

PowerShell 在 stderr 有任何输出时会把"退出码"染成 1（`$LASTEXITCODE` 仍是 0）。
看 stdout 的 `[smoke] OK` 就好。如果你确实需要严格的退出码：

```powershell
& .venv\Scripts\python scripts\smoke_mcp_serve.py 2>$null
$LASTEXITCODE
```

### 5.4 工具调用永远报 `tool_invocation_error`

进 server 的 stderr / 客户端 MCP 日志看堆栈。最常见的是 pcap 文件被 tshark
解出来 0 条记录（路径错、文件损坏、协议无法识别）。先用以下命令确认 tshark
能解出东西：

```powershell
tshark -r "D:\path\to.pcapng" -Y ngap -c 5
```

### 5.5 Claude 不主动调用工具

让它先调 `summarize_capture`：

> 这个对话里你能用 traceweaver 工具。请先调用 `summarize_capture` 拿到 capture overview，再决定下一步。

profile 的 `system.md` 里已有同样指引，但客户端是否注入 system prompt 取决于
客户端实现。Claude Desktop 在每次会话开始时会读取 server 的 system prompt
（通过 MCP `prompts` 资源），M4' MVP 暂未把 profile prompt 暴露为 MCP prompt
资源，因此最稳妥是用户对话首句明确指引。

## 6. 局限与后续

| 项 | 当前状态 | 计划 |
| --- | --- | --- |
| Transport | stdio only | M5+：可选 SSE / HTTP |
| Capture 切换 | 一个 server 一份 pcap | M5+：动态 `set_capture` 工具或 multi-source profile |
| Profile prompt 暴露 | 未通过 MCP prompts 资源透出 | M4'.x：把 profile `system.md` 注册为 MCP prompt |
| 鉴权 | 无（stdio 局限于本机） | 跟 SSE / HTTP 一起做 |

参考：
- 路线图章节 §4 (M4')、§6 (验收清单) — `@d:\code\TraceWeaver\ROADMAP.md`
- CLI 实现 — `@d:\code\TraceWeaver\traceweaver\cli\serve.py`
- MCP 适配层 — `@d:\code\TraceWeaver\traceweaver\serve\mcp.py`
- Smoke 脚本 — `@d:\code\TraceWeaver\scripts\smoke_mcp_serve.py`
