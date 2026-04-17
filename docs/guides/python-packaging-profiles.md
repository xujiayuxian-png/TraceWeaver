# 把 Profile 做成 pip 包分发（入门教程）

面向还不熟悉 Python 打包的同学。本文只讲**能用**，不讲底层原理，跟着做就能把一个
TraceWeaver profile 发布成别人可以 `pip install` 的包。

> **为什么要做这件事**：你写了一个 SIP 行业的 profile，想让同事 `pip install
> traceweaver-profile-sip` 就能用，不用自己拷目录。

---

## 1. 先理解三样东西

| 名词 | 是什么 | 怎么理解 |
|------|--------|---------|
| **包（package）** | 一个目录 + 配置文件 | 相当于一盒药 |
| **pyproject.toml** | 这盒药的标签（名字、版本、成分、使用说明） | 包装盒上的标签 |
| **entry_points** | 这盒药上插的小旗子，告诉别的程序"我提供某种能力" | 药盒上写着"可治感冒" |

TraceWeaver 通过扫描 **entry_points** 里的小旗子 `traceweaver.profiles`
来发现所有安装的 profile。

---

## 2. 最小包结构（复制这个模板就行）

假设你要发布一个叫 `traceweaver-profile-sip` 的 profile，目录结构如下：

```
traceweaver-profile-sip/
├── pyproject.toml                      # 包的标签
├── README.md                           # 给用户看的说明
├── src/
│   └── traceweaver_profile_sip/        # 你的 Python 代码（下划线，不能有减号）
│       ├── __init__.py                 # 空文件即可
│       ├── profile.yaml                # profile 声明文件
│       ├── prompts/
│       │   └── system.md
│       ├── tools/
│       │   ├── __init__.py
│       │   └── get_calls.py
│       └── knowledge/
│           └── sip_causes.md
└── tests/
    └── test_basic.py
```

**注意**：
- 包名（`traceweaver-profile-sip`）可以用连字符（-）
- 模块名（`traceweaver_profile_sip`）必须用下划线（_），这是 Python 的硬性规则
- 源码建议放在 `src/` 下（叫 src layout，比放根目录更稳）

---

## 3. 写 pyproject.toml

这是**关键文件**。下面是可以直接用的模板：

```toml
# 告诉 pip 怎么打包这个项目
[build-system]
requires = ["hatchling>=1.25.0"]
build-backend = "hatchling.build"

# 包的元信息
[project]
name = "traceweaver-profile-sip"
version = "0.1.0"
description = "SIP/VoIP analysis profile for TraceWeaver"
readme = "README.md"
requires-python = ">=3.11"
authors = [
    {name = "Your Name", email = "you@example.com"}
]
license = {text = "MIT"}

# 运行时依赖
dependencies = [
    "traceweaver>=2.0",     # 依赖 TraceWeaver 本体
    # 如果你的工具需要其他库，在这里加
    # "requests>=2.31",
]

# ====================================
# 核心：插上"我是一个 profile"的小旗子
# ====================================
[project.entry-points."traceweaver.profiles"]
# 语法：profile_name = "python.module.path:profile_yaml_filename"
sip = "traceweaver_profile_sip:profile.yaml"

# 如果你还想发布独立工具（跨 profile 用的），也可以插工具旗子
[project.entry-points."traceweaver.tools"]
# compare_rtp_baseline = "traceweaver_profile_sip.tools.compare:CompareRTPBaseline"

# 告诉 hatchling 打包时把哪些文件放进去
[tool.hatch.build.targets.wheel]
packages = ["src/traceweaver_profile_sip"]

# 非 .py 的文件（yaml, md）默认会被忽略，要显式包含
[tool.hatch.build.targets.wheel.force-include]
"src/traceweaver_profile_sip/profile.yaml" = "traceweaver_profile_sip/profile.yaml"
"src/traceweaver_profile_sip/prompts" = "traceweaver_profile_sip/prompts"
"src/traceweaver_profile_sip/knowledge" = "traceweaver_profile_sip/knowledge"
```

**最容易出错的两个地方**：

1. `entry_points` 里的路径：`traceweaver_profile_sip:profile.yaml` 意思是
   "在模块 `traceweaver_profile_sip` 下找 `profile.yaml` 文件"。TraceWeaver 会用
   `importlib.resources` 读它。
2. 非 Python 文件（yaml/md）**默认不会被打包进去**，必须在
   `[tool.hatch.build.targets.wheel.force-include]` 里显式列出。

---

## 4. 本地验证（不发布先跑通）

```bash
# 进入项目目录
cd traceweaver-profile-sip

# 装一个虚拟环境（避免污染全局）
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 以"可编辑模式"安装自己的包，边改边测
pip install -e .

# 验证 TraceWeaver 能发现
traceweaver profile list
# 应该能看到 sip
```

如果 `traceweaver profile list` 没看到，99% 的原因是 `entry_points` 写错了，或者
`profile.yaml` 没被打包进去。排查顺序：

```bash
# 看 entry_points 是否注册成功
python -c "from importlib.metadata import entry_points; \
    print(list(entry_points(group='traceweaver.profiles')))"

# 看 profile.yaml 能不能被读到
python -c "from importlib.resources import files; \
    print(files('traceweaver_profile_sip').joinpath('profile.yaml').read_text()[:200])"
```

---

## 5. 发布到 PyPI（可选，让全世界都能装）

### 5.1 注册 PyPI 账号

去 [pypi.org](https://pypi.org) 注册一个账号，启用 2FA。然后到 Account Settings →
API tokens 生成一个 token（记得保存，只显示一次）。

### 5.2 安装打包工具

```bash
pip install build twine
```

### 5.3 构建

```bash
cd traceweaver-profile-sip
python -m build
# 会在 dist/ 下生成两个文件：
# traceweaver_profile_sip-0.1.0-py3-none-any.whl
# traceweaver_profile_sip-0.1.0.tar.gz
```

### 5.4 上传

第一次建议先传到 TestPyPI 试一下：

```bash
twine upload --repository testpypi dist/*
# 用户名填 __token__，密码填 pypi-xxxx 开头的 token
```

没问题再传正式 PyPI：

```bash
twine upload dist/*
```

### 5.5 别人怎么装

```bash
pip install traceweaver-profile-sip
# TraceWeaver 自动发现这个 profile
traceweaver analyze call.pcap --profile sip
```

---

## 6. 版本管理建议

每次改 profile.yaml 或工具代码，记得把 `pyproject.toml` 的 `version` 递增：

- `0.1.0` → 小 bug 修复 → `0.1.1`
- `0.1.0` → 加了个新工具 → `0.2.0`
- `0.1.0` → 改了 profile.yaml 结构（不兼容） → `1.0.0`

重发同一个版本号会被 PyPI 拒绝，这个限制救过很多次。

---

## 7. 只给团队用，不想发 PyPI 怎么办

有几个选项：

### 7.1 Git 直装（最简单）

把代码推到 GitHub/GitLab 私有仓，别人：

```bash
pip install git+https://github.com/yourcompany/traceweaver-profile-sip.git
```

或指定分支：

```bash
pip install git+https://github.com/yourcompany/traceweaver-profile-sip.git@develop
```

### 7.2 内部 PyPI 镜像（公司有的话）

```bash
twine upload --repository-url https://pypi.your-company.com/ dist/*
```

### 7.3 不搞包分发，直接目录拷贝

TraceWeaver 支持 `~/.traceweaver/profiles/` 目录扫描（**选项 B，M1 优先实现**）。
把整个 profile 目录拷到用户的 `~/.traceweaver/profiles/sip/` 就能用，**完全不需要
pip 包**。对只在团队内部分享来说，这种方式反而更简单。

---

## 8. 常见坑

| 坑 | 症状 | 解决 |
|----|------|-----|
| 包名带下划线 | `pip install` 报找不到包 | 包名用 `-`，模块名用 `_` |
| yaml/md 没打包进去 | 装完包找不到 profile.yaml | `[tool.hatch.build.targets.wheel.force-include]` 显式声明 |
| entry_point 名字写错 | `traceweaver profile list` 看不到 | 严格用 `traceweaver.profiles`（点号分隔）|
| 忘改 version 重发 | PyPI 报 "File already exists" | `version = "0.1.1"` 递增 |
| `src/` layout 没配好 | import 找不到模块 | `packages = ["src/xxx"]` 要写对 |

---

## 9. 这份教程的局限

- 只讲了 hatchling 这一种构建后端（还有 setuptools、poetry、pdm 等）。hatchling
  对新手最友好，所以只推荐这个。
- 没讲 monorepo 多包结构。如果你要一个仓库维护多个 profile，需要额外配置，等有
  真实需求再学。
- 没讲 wheel 架构依赖（有 C 扩展的情况）。纯 Python profile 用不上。

写到这里够你把 profile 发到同事手里了。真发到 PyPI 之前，建议先走一遍 TestPyPI。
