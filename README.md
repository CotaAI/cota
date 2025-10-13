# COTA

COTA (COllaborative Task Agent) 是一个生成式多对话平台，用于构建智能对话机器人和任务执行代理。

## ✨ 特性

- 🤖 **多智能体架构**: 支持 simplebot 和 taskbot 等多种智能体类型
- 💬 **多通道支持**: 命令行、WebSocket、Socket.IO、SSE 等多种交互方式
- 🧠 **LLM 集成**: 支持 OpenAI、DeepSeek、通义千问等主流大语言模型
- 📝 **对话管理**: 内置 DST(对话状态跟踪) 和对话流程控制
- 🔧 **灵活动作系统**: 支持 HTTP 请求、Python 脚本、插件等多种动作执行
- 📚 **RAG 支持**: 内置检索增强生成，支持向量数据库
- 🗄️ **多存储后端**: 内存、MySQL、Redis 等多种数据存储选择

## 🚀 快速开始

### 安装依赖

```bash
# 使用 Poetry (推荐)
poetry install

# 或使用 pip
pip install -r requirements.txt
```

### 运行示例机器人

#### SimpleBot - 简单问答机器人

```bash
cd bots/simplebot
cota run --channel=cmdline
# 或使用 Socket.IO
cota run --channel=socket.io
```

#### TaskBot - 任务执行机器人

```bash
cd bots/taskbot
cota run
```

## 📁 项目结构

```
cota/
├── cota/                   # 核心框架
│   ├── actions/           # 动作执行系统
│   │   ├── action.py     # 基础动作类
│   │   ├── rag.py        # RAG 检索动作
│   │   ├── form.py       # 表单处理
│   │   └── executors/    # 执行器 (HTTP, Python, Script)
│   ├── channels/          # 通信通道
│   │   ├── cmdline.py    # 命令行接口
│   │   ├── websocket.py  # WebSocket 服务
│   │   └── socketio.py   # Socket.IO 服务
│   ├── dpl/              # 对话处理逻辑
│   ├── llm.py            # LLM 集成
│   └── agent.py          # 智能体核心
├── bots/                  # 示例机器人
│   ├── simplebot/        # 简单对话机器人
│   └── taskbot/          # 任务执行机器人
├── docs/                  # 项目文档
└── tests/                 # 测试用例
```

## ⚙️ 配置说明

每个机器人包含两个主要配置文件：

### `endpoints.yml` - 服务端点配置

```yaml
# 数据存储配置
base_store:
  type: Memory  # 或 MySQL
  
# 通道配置  
channel:
  type: Memory  # 或 Redis

# LLM 配置
llm:
  type: api
  apitype: openai
  key: your_api_key
  apibase: your_api_endpoint
```

### `agent.yml` - 智能体配置

```yaml
system:
  description: "智能体的描述和角色设定"

actions:
  # 定义智能体可执行的动作

dialogue:
  # 配置对话流程和策略
```

## 📚 文档

详细文档请参考：
- [快速入门](docs/src/tutorial/quick_start.md)
- [核心概念](docs/src/concepts/)
- [API 文档](docs/)

## 🛠️ 开发

### 环境要求

- Python >= 3.12
- Poetry (推荐) 或 pip

### 运行测试

```bash
pytest tests/
```

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

[许可证信息待添加]
