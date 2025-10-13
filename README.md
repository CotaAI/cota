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

### 📄 许可证

#### 代码许可
代码使用 `MIT License` 发布，允许商业使用和修改。

---

## 🚀 快速开始

### 环境要求

- **Python 3.12+** 
- **Poetry** (推荐) 或 pip
- **Git** 用于代码管理

### 🔧 安装

#### 方法1: 通过Poetry安装 (推荐)

```bash
# 1. 克隆仓库
git clone https://github.com/CotaAI/cota.git
cd cota

# 2. 安装Poetry
pip install poetry

# 3. 安装依赖
poetry install

# 4. 激活虚拟环境
poetry shell
```

#### 方法2: 通过pip安装

```bash
# 1. 创建虚拟环境
python3 -m venv ./venv
source ./venv/bin/activate  # Linux/macOS
# 或 .\venv\Scripts\activate  # Windows

# 2. 克隆仓库
git clone https://github.com/CotaAI/cota.git
cd cota

# 3. 安装依赖
pip install -r requirements.txt
pip install -e .
```

### ⚡ 快速体验

> 确保你在项目根目录下执行以下命令

#### 1. 初始化项目
```bash
# 创建示例机器人配置
cota init
cd cota_projects/simplebot

# 配置API密钥
cp endpoints.yml.example endpoints.yml
# 编辑 endpoints.yml，添加你的LLM API密钥
```

#### 2. 启动命令行对话
```bash
# 启动交互式命令行
cota shell --config=.

# 或启动Web服务
cota run --channel=socket.io --port=5005
```

#### 3. 启动Web界面
```bash
# 启动WebSocket服务
cota run --channel=websocket --host=localhost --port=5005

# 访问 http://localhost:5005 开始对话
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

#### 正式咨询
有关项目和商业合作的正式咨询，请联系：**690714362@qq.com**

#### 社区讨论
##### 1. GitHub Discussions
参与项目讨论：[GitHub Discussions](https://github.com/CotaAI/cota/discussions)

---

<div align="center">

---

**⭐ 如果COTA对你有帮助，请给我们一个Star！**

**⭐ If COTA helps you, please give us a Star!**

![Visitor Count](https://komarev.com/ghpvc/?username=CotaAI&repo=cota&color=blue&style=flat-square)

</div>
