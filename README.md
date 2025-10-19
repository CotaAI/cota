<div align="center">

# COTA
**Chain of Thought Agent Platform for Industrial-Grade Dialogue Systems**

*Simple configuration, reliable performance, powered by annotated policy learning*

[![License](https://img.shields.io/github/license/CotaAI/cota?style=for-the-badge)](https://github.com/CotaAI/cota/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Documentation](https://img.shields.io/badge/Documentation-Available-green?style=for-the-badge)](https://cotaai.github.io/cota/)

[![GitHub Stars](https://img.shields.io/github/stars/CotaAI/cota?style=for-the-badge&logo=github)](https://github.com/CotaAI/cota/stargazers)
[![GitHub Issues](https://img.shields.io/github/issues/CotaAI/cota?style=for-the-badge)](https://github.com/CotaAI/cota/issues)


**[简体中文](#简体中文)** | **[Documentation](https://cotaai.github.io/cota/)**

</div>

## 简体中文

> [!Note]
> 完整的用户文档请访问 [COTA Documentation](https://cotaai.github.io/cota/)

COTA (Chain of Thought Agent) 是一个基于大语言模型的智能体平台，通过**思维链推理**和**标注式策略学习**，让开发者以简单的方式构建可靠的工业级对话系统。

### 💡 核心特征

- **🧠 Chain of Thought 驱动**: 基于思维链推理机制，让AI具备类人的逻辑推理能力
- **📝 标注式策略学习**: 通过标注policies中的thought，训练可靠的对话策略（DPL）
- **🎯 简单易用**: 低代码配置，快速构建生产级智能体

通用LLM往往无法直接承接复杂业务逻辑。如何将业务的策略和大模型结合当前没有解决好，这限制了大模型直接应用到具体业务场景的效果。COTA致力于解决该痛点，COTA将对话策略学习转化为思维生成，充分利用大模型泛化能力的同时确保业务逻辑准确执行。
---

## 🚀 快速开始

### 环境要求

- **Python 3.12+** 
- **pip** 包管理器

### 🔧 安装

#### 方法1: 通过pip安装 (推荐)

```bash
# 1. 安装Python 3.12+
# Ubuntu/Debian:
sudo apt update && sudo apt install python3.12 python3.12-venv python3.12-pip

# macOS (使用Homebrew):
brew install python@3.12

# Windows: 访问 https://www.python.org/downloads/ 下载安装

# 2. 创建虚拟环境
python3.12 -m venv cota-env
source cota-env/bin/activate  # Linux/macOS
# 或 cota-env\Scripts\activate  # Windows

# 3. 安装COTA
pip install cota

# 4. 验证安装
cota --version
```

#### 方法2: 从源码安装 (使用Poetry)

```bash
# 1. 安装Python 3.12+ (同上)

# 2. 安装Poetry
pip install poetry

# 3. 克隆仓库并安装
git clone https://github.com/CotaAI/cota.git
cd cota
poetry install

# 4. 激活虚拟环境
poetry shell

# 5. 验证安装
cota --version
```

### ⚡ 快速体验

> 确保你已按照上述方法安装COTA并激活虚拟环境

#### 1. 初始化项目
```bash
# 创建示例智能体项目
cota init
```

执行后会在当前目录创建 `cota_projects` 文件夹，包含示例配置：

```
cota_projects/
├── simplebot/          # 简单对话机器人
│   ├── agent.yml       # 智能体配置
│   └── endpoints.yml  # LLM配置示例
└── taskbot/           # 任务型机器人
    ├── agents/
    ├── task.yml
    └── endpoints.yml
```

#### 2. 配置智能体
```bash
# 进入simplebot目录
cd cota_projects/simplebot
```

编辑 `endpoints.yml`，配置你的LLM API：

```yaml
llms:
  rag-glm-4:
    type: openai
    model: glm-4                    # 使用的模型名称
    key: your_api_key_here          # 替换为你的API密钥
    apibase: https://open.bigmodel.cn/api/paas/v4/
```

#### 3. 启动对话测试
```bash
# 启动调试模式命令行对话
cota shell --debug

# 或启动普通命令行对话
cota shell --config=.
```

#### 4. 启动服务上线 (可选)
```bash
# 启动WebSocket服务
cota run --channel=websocket --host=localhost --port=5005
```

### 📝 配置说明

`agent.yml` 是智能体的核心配置文件：

```yaml
system:
  description: 你是一个智能助手，你需要认真负责的回答帮用户解决问题

dialogue:
  mode: agent                    # 对话模式
  use_proxy_user: true          # 启用代理用户模拟
  max_proxy_step: 30            # 最大对话轮数
  max_tokens: 500               # LLM响应最大token数

policies:                       # 决策策略配置
  - type: trigger              # 触发式策略
  - type: llm                  # LLM策略
    config:
      llms:
        - name: rag-glm-4      # 默认LLM
        - name: rag-utter      # BotUtter专用LLM
          action: BotUtter
        - name: rag-selector   # Selector专用LLM
          action: Selector
```

## 📚 文档和教程

- **[📖 完整文档](https://cotaai.github.io/cota/)** - 详细的使用指南和API文档
- **[🚀 快速入门](https://cotaai.github.io/cota/tutorial/quick_start.html)** - 5分钟上手指南
- **[⚙️ 配置说明](https://cotaai.github.io/cota/configuration/)** - 智能体和系统配置
- **[🏗️ 架构设计](https://cotaai.github.io/cota/architecture/)** - 深入了解系统架构
- **[🚀 部署指南](https://cotaai.github.io/cota/deployment/)** - 生产环境部署

## 🤝 贡献指南

我们欢迎所有形式的贡献！

1. **Fork** 本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启一个 **Pull Request**


## 📞 联系我们

> GitHub Issues 和 Pull Requests 随时欢迎！
有关项目咨询，请联系：**690714362@qq.com**

#### 社区讨论
##### 1. GitHub Discussions
参与项目讨论：[GitHub Discussions](https://github.com/CotaAI/cota/discussions)

---

<div align="center">

---

**⭐ 如果COTA对你有帮助，请给我们一个Star！**

</div>
