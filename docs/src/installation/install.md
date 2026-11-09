# 安装 Cota

需要 Python 3.12+。使用已发布版本可通过 PyPI 安装；参与开发或使用仓库最新代码时，选择源码安装。

## 当前源码开发

在仓库根目录和 Python 3.12+ 虚拟环境中执行：

```bash
python -m pip install -e '.[dev]'
npm ci --prefix cota/runtime/pi
cota --version
cota --help
```

需要飞书时安装可选依赖：

```bash
python -m pip install -e '.[dev,feishu]'
```

Node.js 至少 22.19，固定开发版本见 `.node-version`。npm 根据已提交的 lockfile 安装固定 Pi 依赖。
editable 安装不自动构建发布包内的运行环境；不要省略源码的 Node/Pi 准备步骤。
使用 uv 的开发者也可用 `uv sync --extra dev --extra feishu --locked` 安装锁定的 Python 环境，然后安装 npm 依赖。

## 安装带运行时的发布包

从 [PyPI](https://pypi.org/project/cota/) 安装已发布版本：

```bash
python -m pip install -U cota
# 飞书为可选能力
python -m pip install -U 'cota[feishu]'
```

带内置运行时的平台 wheel 包含 Cota 与固定版本 Node/Pi，无需额外安装 Node.js/npm，也无需在首次对话时下载执行引擎。
一条 pip 解决的是框架安装，不包括模型服务密钥、外部 MCP 服务、浏览器等业务工具，也不替你创建服务器。

发布构建当前覆盖 macOS 11+ 的 arm64/x86_64、Linux glibc 2.28+ 的 arm64/x86_64。
每个平台的实际产物由 `.github/workflows/runtime-wheels.yml` 在目标环境构建和做安装冒烟验证。
Windows、Alpine 暂无自带运行时的 wheel；普通 `pip install .` 也不能替代带 runtime 的发布构建。
具体构建入口见 [Pi 运行机制](../concepts/pi-runtime.md)。

## 初始化 Bot

```bash
cota init
```

它在当前目录创建 `cota_projects/`，其中仅包含 weather 示例。已有同名目录不会覆盖。
官方模板在仓库根目录 `bots/` 维护；wheel 打包时收录，不再在 Python 主代码里手工维护另一套示例。

填写所选 Bot 的 endpoints.yml，再按 [快速开始](../tutorial/quick_start.md) 启动。
