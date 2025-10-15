# Endpoints配置详解

Endpoints配置文件(`endpoints.yml`)定义了COTA智能体的核心组件连接配置，负责数据存储、通道缓存和大语言模型的统一管理。

## 📋 配置结构

```yaml
base_store:      # 对话数据存储
channel:         # 会话状态缓存  
llms:           # 大语言模型服务
```

## 🗄️ 数据存储配置 (base_store)

**作用**：管理对话历史和会话数据的持久化存储，由`Store`类实现。

### 内存存储 (MemoryStore)
```yaml
base_store:
  type: Memory
```
- **用途**：开发测试环境，数据存储在进程内存中
- **特点**：快速响应，进程重启后数据丢失

### SQL数据库存储 (SQLStore)
```yaml
base_store:
  type: SQL
  dialect: mysql+pymysql    # 数据库驱动
  host: localhost           # 数据库地址
  port: 3306               # 端口
  db: chatbot_db           # 数据库名
  username: ${DB_USER}     # 用户名
  password: ${DB_PASS}     # 密码
  query: {}                # 连接参数(可选)
```

**配置参数**：

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `type` | ✅ | - | 存储类型：Memory/SQL |
| `dialect` | ✅(SQL) | mysql+pymysql | SQLAlchemy方言 |
| `host` | ✅(SQL) | 127.0.0.1 | 数据库主机 |
| `port` | ❌ | 3306 | 数据库端口 |
| `db` | ✅(SQL) | mysql | 数据库名 |
| `username` | ✅(SQL) | root | 用户名 |
| `password` | ✅(SQL) | - | 密码 |
| `query` | ❌ | {} | 额外连接参数 |

**支持的数据库**：
- MySQL: `mysql+pymysql`
- PostgreSQL: `postgresql+psycopg2`  
- SQLite: `sqlite:///path/to/db`

## 🔄 通道缓存配置 (channel)

**作用**：管理会话状态的临时缓存，支持分布式部署。

```yaml
channel:
  type: redis
  host: localhost
  port: 6379
  db: 0
  password: ${REDIS_PASS}   # 可选
```

**配置参数**：

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `type` | ✅ | - | 缓存类型(当前仅支持redis) |
| `host` | ✅ | localhost | Redis主机 |
| `port` | ❌ | 6379 | Redis端口 |
| `db` | ❌ | 0 | Redis数据库号 |
| `password` | ❌ | - | Redis密码 |

## 🤖 大语言模型配置 (llms)

**作用**：配置智能体使用的大语言模型服务，通过`LLMClientFactory`创建客户端实例。

### 配置格式
```yaml
llms:
  model_name:              # 模型标识符
    type: openai          # 客户端类型
    model: actual_name    # 实际模型名
    key: ${API_KEY}       # API密钥
    apibase: https://...  # API地址
```

### 支持的客户端类型

#### 1. OpenAI兼容客户端 (OpenAIClient)
```yaml
llms:
  qwen-max:
    type: openai
    model: qwen-max
    key: ${QWEN_KEY}
    apibase: https://dashscope.aliyuncs.com/compatible-mode/v1
```
- **用途**：标准OpenAI API调用，支持工具调用
- **实现**：`OpenAIClient`类

#### 2. RAG增强客户端 (OpenAIRAGClient)
```yaml
llms:
  rag-glm-4:
    type: openai-rag
    model: glm-4
    key: ${GLM_KEY}
    apibase: https://open.bigmodel.cn/api/paas/v4/
    knowledge_id: "123456"           # 知识库ID
    rag_prompt: "从文档{{knowledge}}中找问题{{question}}的答案"  # RAG提示模板
```
- **用途**：自动添加知识检索功能
- **实现**：`OpenAIRAGClient`类，自动注入检索工具

#### 3. 自定义HTTP客户端 (CustomHttpClient)
```yaml
llms:
  custom-model:
    type: custom
    model: custom-llm
    key: ${CUSTOM_KEY}
    apibase: https://your-api.com/chat
    # 所有额外参数都会传递给HTTP接口
    knowledge_id: "kb123"
    user_id: "user456"
    custom_param: "value"
```
- **用途**：支持任意HTTP API，所有配置参数都传递给接口
- **实现**：`CustomHttpClient`类，最大灵活性

### 通用配置参数

| 参数 | 必需 | 说明 |
|------|------|------|
| `type` | ✅ | 客户端类型：openai/openai-rag/custom |
| `model` | ✅ | 模型名称 |
| `key` | ✅ | API密钥 |
| `apibase` | ✅ | API基础URL |
| `knowledge_id` | ❌ | 知识库ID(仅RAG/custom类型) |
| `rag_prompt` | ❌ | RAG提示模板(仅RAG类型) |

### 常用模型配置示例

**DeepSeek**:
```yaml
deepseek-chat:
  type: openai
  model: deepseek-chat
  key: ${DEEPSEEK_KEY}
  apibase: https://api.deepseek.com/v1
```

**通义千问**:
```yaml
qwen-max:
  type: openai
  model: qwen-max
  key: ${QWEN_KEY}
  apibase: https://dashscope.aliyuncs.com/compatible-mode/v1
```

**ChatGLM RAG**:
```yaml
rag-glm-4:
  type: openai-rag
  model: glm-4
  key: ${GLM_KEY}
  apibase: https://open.bigmodel.cn/api/paas/v4/
  knowledge_id: "1853628378662457344"
  rag_prompt: |
    从文档'''{{knowledge}}'''中找问题'''{{question}}'''的答案，
    找到答案就仅使用文档语句回答，找不到答案就用自身知识回答并告知用户。
```

## 🔐 环境变量配置

推荐所有敏感信息使用环境变量：

```bash
# .env文件
QWEN_KEY=sk-your-qwen-key
DEEPSEEK_KEY=sk-your-deepseek-key
GLM_KEY=your-glm-key.suffix
DB_USER=chatbot_user
DB_PASS=secure_password
REDIS_PASS=redis_secret
```

## 📋 配置模板

### 开发环境
```yaml
base_store:
  type: Memory

channel:
  type: redis
  host: localhost
  port: 6379

llms:
  qwen-max:
    type: openai
    model: qwen-max
    key: ${QWEN_KEY}
    apibase: https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 生产环境
```yaml
base_store:
  type: SQL
  dialect: mysql+pymysql
  host: ${DB_HOST}
  db: ${DB_NAME}
  username: ${DB_USER}
  password: ${DB_PASS}

channel:
  type: redis
  host: ${REDIS_HOST}
  password: ${REDIS_PASS}

llms:
  qwen-max:
    type: openai
    model: qwen-max
    key: ${QWEN_KEY}
    apibase: https://dashscope.aliyuncs.com/compatible-mode/v1
    
  rag-glm-4:
    type: openai-rag
    model: glm-4
    key: ${GLM_KEY}
    apibase: https://open.bigmodel.cn/api/paas/v4/
    knowledge_id: ${KNOWLEDGE_ID}
```