# Endpoints配置详解

Endpoints配置文件(`endpoints.yml`)定义了COTA智能体与外部服务的连接配置，包括数据存储、缓存服务、大语言模型等关键组件的连接信息。

## 📋 配置文件结构

```yaml
base_store:      # 数据存储配置
  type: ...
  host: ...
  
channel:         # 通道缓存配置
  type: ...
  host: ...
  
llms:           # 大语言模型配置
  model_name:
    model: ...
    apitype: ...
```

## 🗄️ 数据存储配置 (base_store)

配置智能体的数据存储后端，支持内存存储和SQL数据库。

### 内存存储配置

```yaml
base_store:
  type: Memory
```

**适用场景**：
- 开发和测试环境
- 临时性对话，无需持久化
- 快速原型开发

### SQL数据库配置

```yaml
base_store:
  type: SQL
  dialect: mysql+pymysql        # 数据库方言
  host: localhost               # 数据库主机
  port: 3306                   # 数据库端口
  db: chatbot_db               # 数据库名称
  username: ${DB_USERNAME}     # 用户名（推荐使用环境变量）
  password: ${DB_PASSWORD}     # 密码（推荐使用环境变量）
  
  # 连接池配置（可选）
  pool_size: 10               # 连接池大小
  max_overflow: 20            # 最大溢出连接数
  pool_timeout: 30            # 连接超时时间
  pool_recycle: 3600         # 连接回收时间
```

**参数说明**：

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `type` | string | ✅ | - | 存储类型：Memory 或 SQL |
| `dialect` | string | ✅ (SQL) | - | SQLAlchemy数据库方言 |
| `host` | string | ✅ (SQL) | localhost | 数据库主机地址 |
| `port` | int | ❌ | 3306 | 数据库端口 |
| `db` | string | ✅ (SQL) | - | 数据库名称 |
| `username` | string | ✅ (SQL) | - | 数据库用户名 |
| `password` | string | ✅ (SQL) | - | 数据库密码 |

**支持的数据库方言**：

| 数据库 | 方言配置 | 依赖包 |
|--------|----------|--------|
| MySQL | `mysql+pymysql` | pymysql |
| PostgreSQL | `postgresql+psycopg2` | psycopg2 |
| SQLite | `sqlite:///` | 内置 |
| SQL Server | `mssql+pyodbc` | pyodbc |

**配置示例**：

```yaml
# MySQL配置
base_store:
  type: SQL
  dialect: mysql+pymysql
  host: db.example.com
  port: 3306
  db: production_chatbot
  username: ${DB_USER}
  password: ${DB_PASS}
  pool_size: 20
  max_overflow: 30

# PostgreSQL配置
base_store:
  type: SQL
  dialect: postgresql+psycopg2
  host: postgres.internal
  port: 5432
  db: chatbot_prod
  username: ${POSTGRES_USER}
  password: ${POSTGRES_PASS}

# SQLite配置（开发环境）
base_store:
  type: SQL
  dialect: sqlite:///./chatbot.db
```

## 🔄 通道缓存配置 (channel)

配置对话通道的缓存服务，主要用于会话状态管理。

### Redis配置

```yaml
channel:
  type: redis
  host: localhost              # Redis主机
  port: 6379                  # Redis端口
  db: 0                       # Redis数据库编号
  password: ${REDIS_PASSWORD} # Redis密码（可选）
  
  # 连接池配置（可选）
  max_connections: 100        # 最大连接数
  socket_timeout: 30          # Socket超时
  socket_connect_timeout: 10  # 连接超时
  retry_on_timeout: true      # 超时重试
  health_check_interval: 30   # 健康检查间隔
```

**参数说明**：

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `type` | string | ✅ | - | 缓存类型，当前支持 redis |
| `host` | string | ✅ | localhost | Redis服务器地址 |
| `port` | int | ❌ | 6379 | Redis端口 |
| `db` | int | ❌ | 0 | Redis数据库编号 |
| `password` | string | ❌ | - | Redis密码 |
| `max_connections` | int | ❌ | 50 | 连接池最大连接数 |

**配置示例**：

```yaml
# 基础Redis配置
channel:
  type: redis
  host: localhost
  port: 6379
  db: 1

# 生产环境Redis配置
channel:
  type: redis
  host: redis-cluster.internal
  port: 6379
  db: 0
  password: ${REDIS_SECRET}
  max_connections: 200
  socket_timeout: 60
  health_check_interval: 30

# Redis Cluster配置
channel:
  type: redis
  host: redis-node1.internal,redis-node2.internal,redis-node3.internal
  port: 6379
  password: ${REDIS_CLUSTER_PASSWORD}
```

## 🤖 大语言模型配置 (llms)

配置智能体使用的大语言模型，支持多种模型服务商。

### 基础配置格式

```yaml
llms:
  model_name:                 # 模型标识符（自定义）
    model: actual_model_name  # 实际模型名称
    apitype: openai          # API类型
    key: ${API_KEY}          # API密钥
    apibase: https://...     # API基础URL
    
    # 可选配置
    userag: true             # 是否使用RAG
    knowledge_id: "12345"    # 知识库ID（RAG模式）
    max_tokens: 4000         # 最大令牌数
    temperature: 0.7         # 随机性控制
    timeout: 60              # 请求超时时间
```

### 支持的模型配置

#### 1. DeepSeek配置

```yaml
llms:
  deepseek-chat:
    model: deepseek-chat
    apitype: openai
    key: ${DEEPSEEK_API_KEY}
    apibase: https://api.deepseek.com/v1
    max_tokens: 4000
    temperature: 0.3
```

#### 2. 通义千问配置

```yaml
llms:
  qwen-max:
    model: qwen-max
    apitype: openai
    key: ${QWEN_API_KEY}
    apibase: https://dashscope.aliyuncs.com/compatible-mode/v1
    max_tokens: 6000
    temperature: 0.5
    
  qwen-turbo:
    model: qwen-turbo
    apitype: openai
    key: ${QWEN_API_KEY}
    apibase: https://dashscope.aliyuncs.com/compatible-mode/v1
    max_tokens: 4000
```

#### 3. ChatGLM配置

```yaml
llms:
  glm-4:
    model: glm-4
    apitype: openai
    key: ${CHATGLM_API_KEY}
    apibase: https://open.bigmodel.cn/api/paas/v4/
    max_tokens: 4000
    
  # RAG模式的ChatGLM配置
  rag-glm-4:
    model: glm-4
    apitype: openai
    key: ${CHATGLM_API_KEY}
    apibase: https://open.bigmodel.cn/api/paas/v4/
    userag: true
    knowledge_id: ${KNOWLEDGE_BASE_ID}
    max_tokens: 2000
```

#### 4. OpenAI配置

```yaml
llms:
  gpt-4:
    model: gpt-4
    apitype: openai
    key: ${OPENAI_API_KEY}
    apibase: https://api.openai.com/v1
    max_tokens: 4000
    temperature: 0.7
    
  gpt-3.5-turbo:
    model: gpt-3.5-turbo
    apitype: openai
    key: ${OPENAI_API_KEY}
    apibase: https://api.openai.com/v1
    max_tokens: 2000
```

#### 5. 自定义API配置

```yaml
llms:
  custom-model:
    model: custom-llm-v1
    apitype: openai           # 使用OpenAI兼容格式
    key: ${CUSTOM_API_KEY}
    apibase: https://your-api.com/v1
    max_tokens: 3000
    temperature: 0.6
    timeout: 120
    
    # 自定义请求头
    headers:
      User-Agent: "COTA-Agent/1.0"
      Custom-Header: "custom-value"
```

### 模型参数说明

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `model` | string | ✅ | - | 具体的模型名称 |
| `apitype` | string | ✅ | - | API类型，目前支持 openai |
| `key` | string | ✅ | - | API访问密钥 |
| `apibase` | string | ✅ | - | API基础URL |
| `userag` | bool | ❌ | false | 是否启用RAG功能 |
| `knowledge_id` | string | ❌ | - | RAG知识库ID |
| `max_tokens` | int | ❌ | 2000 | 单次生成最大令牌数 |
| `temperature` | float | ❌ | 0.7 | 随机性控制 (0-1) |
| `timeout` | int | ❌ | 30 | 请求超时时间（秒） |

## 🔐 安全配置

### 1. 环境变量使用

**推荐做法**：所有敏感信息使用环境变量

```yaml
# endpoints.yml
llms:
  qwen-max:
    key: ${QWEN_API_KEY}      # ✅ 使用环境变量
    # key: sk-actual-key     # ❌ 避免硬编码

base_store:
  username: ${DB_USER}        # ✅ 使用环境变量
  password: ${DB_PASS}        # ✅ 使用环境变量
```

**环境变量设置**：

```bash
# .env文件
QWEN_API_KEY=sk-your-qwen-api-key
DEEPSEEK_API_KEY=sk-your-deepseek-key
CHATGLM_API_KEY=your-chatglm-key.suffix
DB_USER=chatbot_user
DB_PASS=secure_password
REDIS_PASSWORD=redis_secret
```

### 2. 配置文件权限

```bash
# 设置配置文件权限
chmod 600 endpoints.yml
chown app:app endpoints.yml

# 添加到.gitignore
echo "endpoints.yml" >> .gitignore
echo ".env" >> .gitignore
```

### 3. 配置验证

```yaml
# 添加配置验证
validation:
  required_env:
    - QWEN_API_KEY
    - DB_PASSWORD
    - REDIS_PASSWORD
  
  api_connectivity:
    - llm: qwen-max
      test_prompt: "Hello"
    - database: base_store
      test_query: "SELECT 1"
```

## 📊 性能优化配置

### 1. 连接池优化

```yaml
# 数据库连接池
base_store:
  type: SQL
  dialect: mysql+pymysql
  # ... 基础配置 ...
  pool_size: 20              # 常驻连接数
  max_overflow: 30           # 最大额外连接数
  pool_timeout: 30           # 获取连接超时
  pool_recycle: 3600        # 连接回收时间
  pool_pre_ping: true       # 连接健康检查

# Redis连接池
channel:
  type: redis
  # ... 基础配置 ...
  max_connections: 100       # 最大连接数
  retry_on_timeout: true     # 超时重试
  socket_keepalive: true     # TCP keepalive
  socket_keepalive_options:
    TCP_KEEPIDLE: 600
    TCP_KEEPINTVL: 30
    TCP_KEEPCNT: 3
```

### 2. 模型调用优化

```yaml
llms:
  qwen-max:
    # ... 基础配置 ...
    max_tokens: 2000          # 控制生成长度
    temperature: 0.3          # 降低随机性提高一致性
    timeout: 30               # 合理的超时时间
    
    # 请求重试配置
    retry_attempts: 3         # 重试次数
    retry_delay: 1            # 重试延迟
    
    # 并发控制
    max_concurrent: 10        # 最大并发请求
```

## 🔍 监控和日志配置

### 1. 连接监控

```yaml
monitoring:
  database:
    slow_query_threshold: 1.0  # 慢查询阈值（秒）
    connection_pool_alerts: true
    
  redis:
    latency_threshold: 0.1     # 延迟阈值（秒）
    memory_usage_alerts: true
    
  llm:
    response_time_threshold: 5.0  # 响应时间阈值
    error_rate_threshold: 0.05    # 错误率阈值
```

### 2. 日志配置

```yaml
logging:
  database:
    log_slow_queries: true
    log_connection_events: false
    
  redis:
    log_commands: false
    log_connection_events: true
    
  llm:
    log_requests: true
    log_responses: false      # 避免记录敏感内容
    log_tokens_usage: true
```

## 🚨 常见配置错误

### 1. 连接配置错误

```yaml
# ❌ 错误：缺少必需参数
base_store:
  type: SQL
  host: localhost
  # 缺少 dialect, db, username, password

# ✅ 正确：完整配置
base_store:
  type: SQL
  dialect: mysql+pymysql
  host: localhost
  db: chatbot
  username: ${DB_USER}
  password: ${DB_PASS}
```

### 2. API密钥配置错误

```yaml
# ❌ 错误：硬编码密钥
llms:
  qwen-max:
    key: sk-1234567890abcdef  # 安全风险

# ✅ 正确：使用环境变量
llms:
  qwen-max:
    key: ${QWEN_API_KEY}
```

### 3. 网络配置错误

```yaml
# ❌ 错误：不合理的超时配置
llms:
  qwen-max:
    timeout: 1  # 过短，容易超时

# ✅ 正确：合理的超时配置
llms:
  qwen-max:
    timeout: 30  # 30秒，适中
```

## 📚 配置模板

### 开发环境模板

```yaml
# endpoints.yml (开发环境)
base_store:
  type: Memory  # 使用内存存储，简单快速

channel:
  type: redis
  host: localhost
  port: 6379
  db: 0

llms:
  qwen-max:
    model: qwen-max
    apitype: openai
    key: ${QWEN_API_KEY}
    apibase: https://dashscope.aliyuncs.com/compatible-mode/v1
    max_tokens: 2000
    timeout: 30
```

### 生产环境模板

```yaml
# endpoints.yml (生产环境)
base_store:
  type: SQL
  dialect: mysql+pymysql
  host: ${DB_HOST}
  port: 3306
  db: ${DB_NAME}
  username: ${DB_USER}
  password: ${DB_PASS}
  pool_size: 20
  max_overflow: 30
  pool_timeout: 30

channel:
  type: redis
  host: ${REDIS_HOST}
  port: 6379
  db: 0
  password: ${REDIS_PASS}
  max_connections: 100
  socket_timeout: 30

llms:
  qwen-max:
    model: qwen-max
    apitype: openai
    key: ${QWEN_API_KEY}
    apibase: https://dashscope.aliyuncs.com/compatible-mode/v1
    max_tokens: 4000
    temperature: 0.3
    timeout: 45
    
  deepseek-chat:
    model: deepseek-chat
    apitype: openai
    key: ${DEEPSEEK_API_KEY}
    apibase: https://api.deepseek.com/v1
    max_tokens: 4000
    temperature: 0.3
```

通过合理配置Endpoints，你可以确保COTA智能体与外部服务的稳定连接和高效通信。建议在不同环境使用不同的配置文件，并严格管理敏感信息的安全。
