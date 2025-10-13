# 配置说明总览

COTA框架使用YAML格式的配置文件来定义智能体的行为、策略和外部服务连接。一个完整的COTA机器人配置包含以下几个核心部分。

## 📁 配置文件结构

```
simplebot/                    # 机器人项目目录
├── agent.yml               # 智能体配置文件（核心）
├── endpoints.yml            # 端点配置文件（连接配置）
├── endpoints.yml.example    # 端点配置模板
└── policy/                  # 策略配置目录
    ├── data.yml            # 策略数据文件
    ├── rules.yml           # 触发规则文件
    └── *.md                # RAG生成的知识库文件
```

## 🔧 核心配置组件

### 1. Agent配置 (`agent.yml`)
定义智能体的基本信息、对话模式、策略和动作。

**主要配置项**：
- `system`: 智能体基本信息
- `dialogue`: 对话模式和参数
- `policies`: 对话策略配置
- `actions`: 动作定义和提示词

### 2. Endpoints配置 (`endpoints.yml`)
配置外部服务连接，包括数据库、缓存、LLM等。

**主要配置项**：
- `base_store`: 数据存储配置
- `channel`: 通道缓存配置
- `llms`: 大语言模型配置

### 3. Policy配置 (`policy/data.yml`)
定义对话策略和示例，用于训练智能体的对话模式。

**主要配置项**：
- `policies`: 策略示例列表
- 每个策略包含完整的对话流程示例

### 4. Trigger配置 (`policy/rules.yml`)
定义触发规则，当用户输入匹配特定模式时自动执行相应动作。

**主要配置项**：
- `triggers`: 触发规则列表
- 每个规则包含触发条件和执行动作

## 🚀 快速配置流程

### 1. 创建基础结构
```bash
mkdir mybot
cd mybot
mkdir policy
```

### 2. 复制配置模板
```bash
# 复制端点配置模板
cp endpoints.yml.example endpoints.yml
# 编辑并填入实际配置
```

### 3. 配置优先级
配置文件的加载和覆盖优先级：
1. `agent.yml` - 核心配置，必须存在
2. `endpoints.yml` - 连接配置，必须存在
3. `policy/data.yml` - 策略数据，可选
4. `policy/rules.yml` - 触发规则，可选

### 4. 环境变量支持
为了安全起见，敏感信息支持环境变量：

```yaml
# endpoints.yml中使用环境变量
llms:
  qwen-max:
    key: ${QWEN_API_KEY}  # 从环境变量读取
    
# 设置环境变量
export QWEN_API_KEY="your-actual-api-key"
```

## ⚙️ 配置模式

### 1. 简单模式
最小化配置，适合快速原型开发：

```yaml
# agent.yml (简化版)
system:
  description: "简单智能助手"

dialogue:
  mode: agent

policies:
  - name: trigger

actions:
  UserUtter:
    description: "用户提问"
  BotUtter:
    description: "机器人回复"
```

### 2. 完整模式
全功能配置，适合生产环境：

```yaml
# agent.yml (完整版)
system:
  description: "智能客服助手"

dialogue:
  mode: agent
  max_bot_step: 20
  use_proxy_user: true
  max_tokens: 500

policies:
  - name: trigger
  - name: match
  - name: rag
    llm: qwen-max

actions:
  UserUtter: {...}
  BotUtter: {...}
  Selector: {...}
  # 更多自定义动作...
```

## 🔍 配置验证

### 1. 必须配置项检查
- `system.description`: 智能体基本描述
- `dialogue.mode`: 对话模式
- `policies`: 至少一个策略
- `actions.UserUtter`: 用户输入动作
- `actions.BotUtter`: 机器人回复动作

### 2. 配置文件语法验证
```bash
# 验证YAML语法
python -c "import yaml; yaml.safe_load(open('agent.yml'))"

# 检查配置完整性
python -m cota.validate_config --path ./mybot
```

## 📚 配置最佳实践

### 1. 模块化配置
- 将复杂的提示词放在单独的文件中
- 使用环境变量管理敏感信息
- 为不同环境创建不同的配置文件

### 2. 版本控制
- 配置文件纳入版本控制
- 敏感配置文件添加到 `.gitignore`
- 提供配置模板文件

### 3. 文档化
- 为每个配置项添加注释说明
- 维护配置变更日志
- 提供配置示例和最佳实践

## 🚨 常见配置错误

### 1. YAML语法错误
```yaml
# ❌ 错误：缩进不一致
system:
  description: "助手"
 policies:  # 缩进错误
  - name: trigger

# ✅ 正确：保持一致的缩进
system:
  description: "助手"
policies:
  - name: trigger
```

### 2. 配置项缺失
```yaml
# ❌ 错误：缺少必需配置
system:
  description: "助手"
# 缺少 dialogue 和 actions 配置

# ✅ 正确：包含必需配置
system:
  description: "助手"
dialogue:
  mode: agent
actions:
  UserUtter:
    description: "用户输入"
```

### 3. 策略配置错误
```yaml
# ❌ 错误：策略名称不存在
policies:
  - name: unknown_policy  # 不支持的策略

# ✅ 正确：使用支持的策略
policies:
  - name: trigger
  - name: match
  - name: rag
```

## 🔗 相关链接

- [Agent配置详解](agent.md) - 详细的智能体配置说明
- [Endpoints配置详解](endpoints.md) - 外部服务连接配置
- [Policy配置详解](policy.md) - 策略和示例配置
- [Trigger配置详解](trigger.md) - 触发规则配置

通过合理的配置，你可以创建功能强大、响应准确的COTA智能体。建议从简单配置开始，逐步添加高级功能。
