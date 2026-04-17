# Windows 环境测试技能

## 概述

在 Windows 上运行 TraceWeaver 测试时可能遇到的常见环境问题和解决方法。

## 问题 1: tshark 输出编码错误

### 症状
```
UnicodeDecodeError: 'gbk' codec can't decode byte 0x... in position ...
```

或捕获输出时出现乱码、解码失败。

### 根本原因
Windows 默认使用 GBK 编码，而 tshark 输出包含 UTF-8 字符（如国际化的协议字段名、非 ASCII 字符等）。

### 解决方法

在调用 `subprocess.run` 时明确指定编码参数：

```python
# traceweaver/tshark/tools.py 和 traceweaver/tshark/extract.py
result = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    encoding='utf-8',      # 强制使用 UTF-8
    errors='replace'       # 无法解码的字符用 替换，避免崩溃
)
```

### 验证修复
```bash
python -c "from traceweaver.tshark.tools import get_tshark_version; print(get_tshark_version())"
```

## 问题 2: Ollama qwen3.5 OpenAI 兼容接口返回空 content

### 症状
LLM 调用返回空字符串或 JSON 解析失败，诊断降级为 fallback。

### 根本原因
Ollama 的 OpenAI 兼容接口在 qwen3.5 模型上默认开启 thinking 模式，将输出放在 `reasoning` 字段而非 `message.content` 中。

### 解决方法

在调用 litellm 时注入 `extra_body` 参数关闭 thinking：

```python
# traceweaver/llm/provider.py
from litellm import completion

def complete(self, system_prompt: str, user_prompt: str) -> str:
    extra_body = None
    # Ollama qwen3 模型默认开启 thinking，会导致 content 为空
    if self.config.model.startswith("ollama/qwen3"):
        extra_body = {"think": False}
    
    response = completion(
        model=self.config.model,
        messages=[...],
        extra_body=extra_body,  # 禁用 thinking 模式
    )
    return response.choices[0].message.content
```

### 验证修复
```bash
python -c "
from traceweaver.llm import LLMProvider, LLMConfig
config = LLMConfig(model='ollama/qwen3.5:9b')
llm = LLMProvider(config)
result = llm.complete('You are a tester.', 'Say hello')
print('Result:', result)
assert result and len(result) > 0, 'LLM returned empty content'
print('OK: LLM returns non-empty content')
"
```

## 问题 3: PATH 中找不到 tshark

### 症状
```
FileNotFoundError: [WinError 2] 系统找不到指定的文件
tshark not found in PATH
```

### 解决方法

**临时方案**（当前终端会话）：
```powershell
$env:PATH += ";C:\Program Files\Wireshark"
python -m traceweaver analyze test.pcapng
```

**永久方案**（系统环境变量）：
1. 右键"此电脑" → 属性 → 高级系统设置 → 环境变量
2. 编辑系统变量 `PATH`
3. 添加 `C:\Program Files\Wireshark`
4. 重启终端

**验证**：
```powershell
tshark --version
```

## 问题 4: Ollama 服务未启动

### 症状
```
ConnectionRefusedError: [WinError 10061] 由于目标计算机积极拒绝，无法连接
```

### 解决方法

**启动 Ollama 服务**：
```powershell
# 前台运行（调试时使用）
ollama serve

# 或后台运行（新开终端）
Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
```

**验证**：
```powershell
ollama list
ollama run qwen3.5:9b "Hello"
```

## 问题 5: Python 虚拟环境路径含空格或特殊字符

### 症状
某些脚本在 PowerShell 中执行时，虚拟环境路径解析失败。

### 解决方法

使用完整路径调用 Python，避免相对路径问题：

```powershell
# 推荐
d:\code\TraceWeaver\.venv\Scripts\python.exe script.py

# 避免（可能在某些环境下出问题）
.venv\Scripts\python script.py
```

## 快速检查清单

运行测试前确认：

- [ ] `tshark --version` 能正常显示版本
- [ ] `ollama list` 显示 qwen3.5:9b 模型
- [ ] `ollama serve` 已启动（或 Ollama 托盘程序在运行）
- [ ] Python 虚拟环境已激活（或直接使用完整路径）
- [ ] 测试抓包文件路径正确（Windows 使用 `\` 或正斜杠）

## 测试命令模板

```powershell
# 设置环境
$env:PATH += ";C:\Program Files\Wireshark"

# 单次诊断
d:\code\TraceWeaver\.venv\Scripts\python.exe -m traceweaver analyze tests/fixtures/pcap/07_pfcp_failure.pcapng --model ollama/qwen3.5:9b

# Investigation 模式
d:\code\TraceWeaver\.venv\Scripts\python.exe -m traceweaver investigate tests/fixtures/pcap/07_pfcp_failure.pcapng --model ollama/qwen3.5:9b

# 运行实验脚本
cd d:\code\TraceWeaver\experiments
d:\code\TraceWeaver\.venv\Scripts\python.exe show_open_investigation.py
```

## 相关代码文件

修复涉及的源文件：
- `traceweaver/tshark/tools.py` - tshark 编码修复
- `traceweaver/tshark/extract.py` - tshark 编码修复
- `traceweaver/llm/provider.py` - Ollama qwen3 thinking 模式修复
- `tests/test_llm.py` - 包含这些行为的测试覆盖
