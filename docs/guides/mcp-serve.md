# MCP 接入指南：Claude Desktop / Cursor / Cline

`traceweaver serve` 把 profile 的工具集合通过 [Model Context Protocol](https://modelcontextprotocol.io/)
暴露给外部 agent。配一次，反复用——抓包文件由 agent 在对话中动态加载。

> 适用版本：M4'+（stdio transport，多 profile 支持，运行时 load_capture）。

## 前置条件

| 项 | 要求 |
| --- | --- |
| Python | ≥ 3.11，venv 内 `pip install -e ".[mcp-server]"` 完成 |
| tshark | 安装并加入 PATH |
| MCP 客户端 | Claude Desktop / Cursor / Cline 任一 |

```bash
# 确认 traceweaver 可用
traceweaver serve --help

# 确认 tshark 可用
tshark --version
```

## 最小配置

**配置文件**（只需写一次，不用改）：

```json
{
  "mcpServers": {
    "traceweaver": {
      "command": "traceweaver",
      "args": ["serve", "--profile", "open5gs_5gc"]
    }
  }
}
```

**多 profile**：

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

> 配置里没有 `--pcap`。抓包文件由 agent 在对话中通过 `load_capture` 工具加载。

## 使用流程

```
用户: 帮我分析一下 /tmp/registration_failure.pcapng
Agent: [调用 load_capture(path="/tmp/registration_failure.pcapng")]
       [调用 summarize_capture → list_ue_sessions → get_ue_timeline]
       [返回诊断结果]

用户: 再看下这个 /tmp/another.pcapng
Agent: [调用 load_capture(path="/tmp/another.pcapng")]   ← 换抓包，不用重启
       [继续分析]
```

## 可用的元工具

| 工具 | 用途 |
| --- | --- |
| `load_capture` | 加载一个 pcap/pcapng 文件（可反复调用换文件） |
| `list_profiles` | 列出已加载的 profile 及默认 profile |
| `list_captures` | 查看每个 profile 当前加载了哪个抓包 |

多 profile 模式下，profile 专属工具自动加前缀（如 `open5gs_5gc__summarize_capture`），
内置工具（`query_records`、`search_knowledge`）无前缀，路由到默认 profile。

## Claude Desktop 配置

Windows 路径：`%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "traceweaver": {
      "command": "D:\\code\\TraceWeaver\\.venv\\Scripts\\traceweaver.exe",
      "args": ["serve", "--profile", "open5gs_5gc"],
      "env": {
        "PATH": "C:\\Program Files\\Wireshark;${PATH}"
      }
    }
  }
}
```

保存后**完全重启 Claude Desktop**（菜单 → Quit，再启动）。

## Cursor / Cline 配置

配置 schema 与 Claude Desktop 一致，照抄即可：

- **Cursor**：设置 → Features → MCP，或编辑 `~/.cursor/mcp.json`
- **Cline**：VS Code 命令面板 → "Cline: Open MCP Settings"

## 错误排查

### 看不到工具

1. 查看 MCP 日志（Claude Desktop：`%APPDATA%\Claude\logs\mcp*.log`）
2. 最常见原因：tshark 不在 PATH

### stderr 有 banner 但 stdout 无数据

正常。`traceweaver serve` 向 stderr 打印状态，stdout 全部给 MCP 协议用。

### 工具调用报错

看 stderr 堆栈。最常见：pcap 路径错误或文件损坏。先确认 tshark 能解析：

```bash
tshark -r /path/to.pcapng -c 5
```

### Agent 不主动调工具

首句明确指引：

> 请先调 `load_capture` 加载抓包，再调 `summarize_capture` 开始分析。

## Windows 特殊处理

PowerShell 的 GBK 编码可能导致输出乱码，`traceweaver serve` 已自动切 UTF-8。
如仍有问题，设置环境变量：

```powershell
$env:PYTHONIOENCODING = "utf-8"
```
