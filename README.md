<div align="center">

# COTA
**Chain of Thought Agent Platform for Industrial-Grade Dialogue Systems**

*Simple configuration, reliable performance*

[![License](https://img.shields.io/github/license/CotaAI/cota?style=for-the-badge)](https://github.com/CotaAI/cota/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Documentation](https://img.shields.io/badge/Documentation-Available-green?style=for-the-badge)](https://cotaai.github.io/cota/)
[![知乎专栏](https://img.shields.io/badge/知乎专栏-智能体框架-blue?style=for-the-badge)](https://www.zhihu.com/column/c_1804161563009093633)

[![GitHub Stars](https://img.shields.io/github/stars/CotaAI/cota?style=for-the-badge&logo=github)](https://github.com/CotaAI/cota/stargazers)
[![GitHub Issues](https://img.shields.io/github/issues/CotaAI/cota?style=for-the-badge)](https://github.com/CotaAI/cota/issues)


**[简体中文](#简体中文)** | **[Documentation](https://cotaai.github.io/cota/)** | **[知乎专栏](https://www.zhihu.com/column/c_1804161563009093633)**

</div>

---

通用大模型在特定业务场景中面临**诸多痛点**：

1. **领域知识融合难**
   通用LLM缺乏垂直领域专业能力，如何低成本注入领域知识？

2. **业务逻辑执行不可靠**
   复杂业务流程无法准确执行，AI决策缺乏可追溯性

3. **开发成本高** 
   传统Agent框架概念复杂（状态机、图编排），需要深度理解AI系统


### COTA可以做什么 ✅

COTA采用**标注式策略学习**，将领域知识以思维链的形式注入：

```
1. 用户编写对话示例 → 标注思维过程 (thought)
2. COTA学习思维模式 → 构建决策策略 (DPL)
3. 新对话触发 → 检索相似思维 → 执行可靠决策
```

**无需学习Agent复杂概念，只需编辑对话！**，COTA自动学习业务策略，构建可靠的领域AI助理。如果你会写对话，就会用COTA!


```yaml
# 无需理解Agent概念，只需编写带思维链的对话示例
policies:
  - title: "复杂查天气"
    actions:
      - name: UserUtter
        result: "成都和重庆天气咋样哪个好"
      - name: Selector
        thought: "用户询问两个城市天气，需要先查成都，再查重庆，然后比较"
        result: Weather
      - name: Weather
        result: <成都天气结果>
      - name: Selector
        thought: "已拿到成都天气，还需要查询重庆天气"
        result: Weather
      - name: Weather
        result: <重庆天气结果>
      - name: BotUtter
        thought: "比较两个城市天气，告诉用户哪个更适合旅游"
        result: "成都晴20℃，重庆阴18℃，建议去成都"
```
### 🧠 核心特性

- **📝 零代码配置**: 通过YAML编写对话示例即可定义业务策略，无需复杂的编程知识
- **🧩 思维链驱动**: 基于Chain of Thought机制，让AI具备类人逻辑推理能力
- **🎓 标注式学习**: 通过标注对话中的`thought`字段，自动学习可靠对话策略（DPL）
- **🏗️ 经典框架**: 遵循领域成熟的Dialogue State Tracker (DST) 架构，稳定可靠
- **🔧 工业级可用**: 内置多轮对话、Form填写、Action执行等生产级能力

### 🎯 核心优势

| 特性 | 传统Agent框架 | COTA |
|------|--------------|------|
| **学习成本** | 需要理解状态机、图编排 | ✅ 只需要写对话 |
| **开发周期** | 需要设计复杂系统 | ✅ 标注思维链即可 |
| **领域知识融合** | 需要微调模型 | ✅ 编写对话示例 |
| **可追溯性** | 黑盒决策 | ✅ 思维链可追踪 |
| **可靠性** | 需要大量测试 | ✅ 基于DST框架，稳定可靠 |

---

**三类开发者优先选择 COTA：**

| 开发者类型 | 选择理由 |
|---------|---------|
| **业务开发者** | 无需学习Agent框架，用熟悉的对话编写业务逻辑 |
| **领域专家** | 只需编辑对话示例，不写代码也能构建AI助手 |
| **AI工程师** | 实现思维链到策略的自动化学习，保障可追溯性 |

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

## 📚 完整文档

- **[📖 完整文档](https://cotaai.github.io/cota/)** - 详细使用指南和API文档
- **[📝 知乎专栏](https://www.zhihu.com/column/c_1804161563009093633)** - 智能体框架深度解析和实践案例
- **[🚀 5分钟快速入门](https://cotaai.github.io/cota/tutorial/quick_start.html)** - 从零开始构建你的第一个AI助手
- **[⚙️ 配置详解](https://cotaai.github.io/cota/configuration/)** - 了解agent.yml、endpoints.yml配置
- **[🎓 DPL策略学习](https://cotaai.github.io/cota/concepts/dpl/)** - 学习如何通过标注思维链构建可靠策略
- **[🏗️ 架构原理](https://cotaai.github.io/cota/)** - DST、Action、Channel等核心概念
- **[🚀 生产部署](https://cotaai.github.io/cota/deployment/)** - 部署到生产环境的最佳实践

## 🤝 贡献指南

我们欢迎所有形式的贡献！

1. **Fork** 本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启一个 **Pull Request**


## English

<details>
<summary><b>Click to expand English version</b></summary>

### Problem & Solution

**The Challenge You Face:**

General LLMs struggle with three critical issues in domain-specific scenarios:

1. **Domain Knowledge Integration is Difficult** ❌  
   How to low-cost inject domain expertise into general LLMs?

2. **Unreliable Business Logic Execution** ❌  
   Complex business processes cannot be accurately executed

3. **High Development Cost** ❌  
   Traditional Agent frameworks require deep understanding of AI systems

**COTA's Solution** ✅

**Transform domain knowledge into chain of thought, making AI think like experts**

Just edit dialogue text with annotated thought processes, and COTA automatically learns business strategies to build reliable domain AI assistants.

### Key Features

- **📝 Zero-Code Configuration**: Define business strategies by writing dialogue examples in YAML
- **🧩 Chain of Thought Driven**: Based on CoT mechanism for human-like reasoning
- **🎓 Annotated Learning**: Automatically learn dialogue policies (DPL) by annotating `thought` field
- **🏗️ Classic Framework**: Built on proven Dialogue State Tracker (DST) architecture
- **🔧 Production-Ready**: Multi-turn dialogue, Form filling, Action execution

### Quick Start

```bash
# Install
pip install cota

# Initialize
cota init

# Start
cota shell --debug
```

**Learn More**: [📖 Documentation](https://cotaai.github.io/cota/)

</details>

---

## 📞 联系我们

> GitHub Issues 和 Pull Requests 随时欢迎！  
> 项目咨询：**690714362@qq.com**

**社区讨论**: [GitHub Discussions](https://github.com/CotaAI/cota/discussions)

---

<div align="center">

**⭐ 如果COta对你有帮助，请给我们一个Star！这将是对我们最好的鼓励！⭐**

Made with ❤️ by [CotaAI](https://github.com/CotaAI)

</div>
