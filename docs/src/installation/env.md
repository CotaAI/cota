# 环境准备

Cota 源码要求 **Python 3.12+**。运行当前源码还需要 **Node.js 22.19+ 和 npm**；仓库 `.node-version` 给出开发固定版本。
发布的平台 wheel 可以自带 Node/Pi，使用该类发布包时不要求用户另装 Node/npm。

## Python 虚拟环境

已有 Python 3.12 时：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python --version
```

也可以使用已安装的 uv：

```bash
uv venv --python 3.12
source .venv/bin/activate
```

激活环境只决定 Python 和命令的位置，不会配置模型密钥。模型 key、apibase、model 直接填写在 Bot 的 endpoints.yml。
当前发布目标是 macOS 和 Linux；Windows/Alpine 不属于已配置的平台 wheel 目标，不应直接照抄部署结论。

## 源码运行前检查

```bash
python --version
node --version
npm --version
```

安装步骤见 [安装 Cota](install.md)。数据库路径、外部工具和模型服务仍由 Bot 的部署配置决定。
