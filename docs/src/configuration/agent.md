# Agent配置详解

Agent配置文件(`agent.yml`)是COTA智能体的核心配置，定义了智能体的基本信息、对话模式、策略配置和动作定义。

## 📋 配置文件结构

```yaml
system:          # 智能体基本信息
  description: ...
  
dialogue:        # 对话配置
  mode: ...
  max_bot_step: ...
  
policies:        # 策略配置
  - name: ...
  
actions:         # 动作定义
  ActionName: ...
```

## 🔧 详细配置说明

### 1. System配置

定义智能体的基本信息和身份。

```yaml
system:
  description: "你是一个智能助手，需要认真负责地回答用户问题"
  name: "assistant"  # 可选，智能体名称
```

**参数说明**：

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `description` | string | ✅ | - | 智能体的角色描述，影响对话风格和行为 |
| `name` | string | ❌ | "agent" | 智能体名称，用于日志和调试 |

**配置示例**：

```yaml
# 客服助手
system:
  description: "你是一个专业的客服助手，需要耐心、礼貌地解决用户问题"
  name: "customer_service"

# 医疗咨询助手  
system:
  description: "你是一名专业的医疗咨询助手，提供准确的医疗建议"
  name: "medical_assistant"

# 技术支持助手
system:
  description: "你是一个技术支持专家，帮助用户解决技术问题"
  name: "tech_support"
```

### 2. Dialogue配置

控制对话的模式和参数。

```yaml
dialogue:
  mode: agent                    # 对话模式
  max_bot_step: 20              # 最大机器人步数
  use_proxy_user: false         # 是否使用代理用户
  max_proxy_user_step: 20       # 最大代理用户步数
  use_proxy_user_breaker: true  # 是否使用代理用户中断器
  max_tokens: 500               # 最大令牌数
```

**参数说明**：

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `mode` | string | ✅ | "agent" | 对话模式，当前支持 "agent" |
| `max_bot_step` | int | ❌ | 10 | 单次对话中机器人最大执行步数 |
| `use_proxy_user` | bool | ❌ | false | 是否启用代理用户模式 |
| `max_proxy_user_step` | int | ❌ | 10 | 代理用户模式下的最大步数 |
| `use_proxy_user_breaker` | bool | ❌ | true | 是否使用代理用户中断器 |
| `max_tokens` | int | ❌ | 1000 | LLM生成的最大令牌数 |

**配置示例**：

```yaml
# 简单对话模式
dialogue:
  mode: agent
  max_bot_step: 10

# 复杂交互模式
dialogue:
  mode: agent
  max_bot_step: 30
  use_proxy_user: true
  max_proxy_user_step: 15
  max_tokens: 800

# 快速响应模式
dialogue:
  mode: agent
  max_bot_step: 5
  max_tokens: 200
```

### 3. Policies配置

定义智能体使用的对话策略。

```yaml
policies:
  - name: trigger              # 触发式策略
  - name: match               # 匹配式策略
  - name: rag                 # RAG策略
    llm: qwen-max            # 单一LLM配置
  - name: rag                 # RAG策略（高级配置）
    llm:                     # 多LLM配置
      BotUtter: qwen-max     # 回复动作使用qwen-max
      Selector: deepseek-chat # 选择动作使用deepseek-chat
      default: glm-4         # 默认LLM
    max_thoughts: 5          # 最大思维链数量
```

**策略类型说明**：

| 策略名称 | 说明 | 适用场景 |
|----------|------|----------|
| `trigger` | 基于规则的触发策略 | 简单的触发响应 |
| `match` | 基于模式匹配的策略 | 复杂的对话模式匹配 |
| `rag` | 检索增强生成策略 | 需要外部知识的对话 |

**RAG策略配置参数**：

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `llm` | string/object | ✅ | - | LLM配置，支持字符串或对象格式 |
| `max_thoughts` | int | ❌ | 5 | 最大思维链生成数量 |

**配置示例**：

```yaml
# 基础策略组合
policies:
  - name: trigger
  - name: match

# RAG策略（单一LLM）
policies:
  - name: rag
    llm: qwen-max
    max_thoughts: 3

# 多策略组合（按优先级）
policies:
  - name: trigger     # 优先级最高
  - name: match       # 其次匹配
  - name: rag         # 最后RAG生成
    llm:
      BotUtter: qwen-max
      Selector: deepseek-chat
      default: glm-4
```

### 4. Actions配置

定义智能体可以执行的动作。

#### 4.1 基础动作

**UserUtter - 用户输入动作**

```yaml
UserUtter:
  description: "用户向智能体提问"
  prompt: |
    历史对话:
    {{history_messages}}
    
    请输出对智能体说的话
    
  breaker:  # 可选：对话中断判断
    description: "判断是否结束对话"
    prompt: |
      根据对话内容，判断对话是否可以结束
      
      对话内容:
      {{history_messages}}
      
      如果对话完整且可以结束，输出true
      如果对话还需要继续，输出false
      
      输出格式：<标识符>
```

**BotUtter - 机器人回复动作**

```yaml
BotUtter:
  description: "回复用户"
  prompt: |
    你是一个智能助手，需要根据对话历史生成合适的回复。
    
    **任务描述：**
    {{task_description}}
    
    **输出格式要求：**
    你必须严格按照以下JSON格式响应：
    ```json
    {"thought": "<推理过程>", "text": "<回复内容>"}
    ```
    
    **学习参考资料：**
    {{thoughts}}
    
    **对话历史：**
    {{history_actions}}
    
    请生成合适的JSON格式回复：
```

**Selector - 动作选择器**

```yaml
Selector:
  description: "选择合适的Actions"
  prompt: |
    你是一个智能对话助手，需要选择下一个最合适的Action。
    
    **输出格式要求：**
    ```json
    {"thought": "<推理过程>", "action": "<工具名称>"}
    ```
    
    **可用的Action工具：**
    {{action_descriptions}}
    
    **决策参考模式：**
    {{thoughts}}
    
    **当前对话状态：**
    {{history_actions}}
    
    请选择最合适的Action：
```

#### 4.2 Form动作（表单填充）

Form动作用于收集用户信息和执行外部API调用。

```yaml
Weather:  # 天气查询动作示例
  description: "查询天气信息"
  prompt: |
    当前正在执行{{current_form_name}}，描述：{{current_form_description}}
    
    查询结果：{{current_form_execute_result}}
    
    你必须严格按照以下JSON格式响应：
    {"text": "<回复内容>"}
    
  updater:  # 状态更新器
    description: "更新槽位状态"
    prompt: |
      当前正在执行{{current_form_name}}，描述：{{current_form_description}}
      
      历史Action序列：{{history_actions}}
      当前slots：{{current_form_slot_states}}
      slots含义：{{current_form_slot_descriptions}}
      
      请填充或重置slot的值，输出JSON格式
      
  slots:  # 槽位定义
    city:
      description: "城市名称，接口只支持单个城市"
      prompt: |
        当前正在执行{{current_form_name}}，需要询问用户查询哪个城市的天气。
        你必须严格按照JSON格式响应：
        {"text": "<询问内容>"}
        
    time:
      description: "查询时间"
      prompt: |
        需要询问用户查询哪天的天气。
        {"text": "<询问内容>"}
        
  executer:  # 执行器配置
    type: http
    url: "http://api.weather.com/v1/current"
    method: GET
    client_key: default
    output: ["<text>", "接口异常"]
    mock: false  # 是否使用模拟数据
```

#### 4.3 自定义动作

```yaml
Calculate:  # 计算器动作
  description: "执行数学计算"
  prompt: |
    当前正在执行计算功能，计算结果：{{current_form_execute_result}}
    
    请将结果返回给用户，不要自己计算。
    {"text": "<回复内容>"}
    
  slots:
    expression:
      description: "数学表达式，如：1+1, 2*3等"
      prompt: |
        请输入需要计算的数学表达式：
        {"text": "<询问内容>"}
        
  executer:
    type: http
    url: "http://calc.api.com/calculate"
    method: POST
    output: ["<text>", "计算错误"]
    mock: true

CustomAction:  # 完全自定义动作
  description: "自定义业务逻辑"
  prompt: |
    根据业务需求执行自定义逻辑
    
    输入参数：{{custom_params}}
    历史对话：{{history_messages}}
    
    输出结果：
    {"text": "<处理结果>", "data": "<业务数据>"}
```

## 🔧 高级配置

### 1. 模板变量

Action的prompt支持丰富的模板变量：

| 变量名 | 说明 | 使用场景 |
|--------|------|----------|
| `{{task_description}}` | 任务描述 | 所有Action |
| `{{history_messages}}` | 历史消息 | UserUtter, BotUtter |
| `{{history_actions}}` | 历史动作序列 | Selector, BotUtter |
| `{{thoughts}}` | 思维链参考 | RAG策略下的Action |
| `{{action_descriptions}}` | 动作描述列表 | Selector |
| `{{current_form_name}}` | 当前表单名称 | Form动作 |
| `{{current_form_slot_states}}` | 当前槽位状态 | Form动作的updater |
| `{{current_form_execute_result}}` | 执行结果 | Form动作 |

### 2. JSON格式约定

所有Action的输出都应遵循JSON格式约定：

```yaml
# BotUtter输出格式
{"thought": "我的推理过程", "text": "回复内容"}

# Selector输出格式  
{"thought": "选择理由", "action": "动作名称"}

# Form动作输出格式
{"text": "回复内容"}

# 自定义输出格式
{"text": "回复内容", "data": "业务数据", "status": "状态"}
```

### 3. 执行器配置

Form动作的执行器支持多种类型：

```yaml
executer:
  type: http           # 执行器类型：http, script, python, plugin
  url: "http://..."    # API地址
  method: GET          # HTTP方法
  headers:             # 请求头
    Authorization: "Bearer token"
    Content-Type: "application/json"
  client_key: default  # HTTP客户端配置键
  output: ["<text>", "错误信息"]  # 预期输出格式
  mock: false          # 是否使用模拟数据
  timeout: 30          # 超时时间（秒）
```

## 📚 最佳实践

### 1. 提示词设计

- **明确指令**：使用清晰、具体的指令
- **格式约束**：严格要求JSON输出格式
- **上下文利用**：合理使用模板变量
- **错误处理**：考虑异常情况的处理

### 2. 动作组织

- **单一职责**：每个Action专注一个功能
- **合理粒度**：避免动作过于复杂或过于简单
- **依赖管理**：明确动作间的依赖关系
- **复用设计**：设计可复用的通用动作

### 3. 性能优化

- **缓存利用**：合理使用模板变量缓存
- **并发控制**：避免过多同时执行的动作
- **资源管理**：及时清理不需要的资源
- **监控报警**：添加关键指标监控

## 🚨 常见错误

### 1. 配置语法错误

```yaml
# ❌ 错误：YAML语法错误
actions:
  UserUtter:
    description "用户输入"  # 缺少冒号

# ✅ 正确：标准YAML语法
actions:
  UserUtter:
    description: "用户输入"
```

### 2. 必需字段缺失

```yaml
# ❌ 错误：缺少description
actions:
  UserUtter:
    prompt: "..."

# ✅ 正确：包含必需字段
actions:
  UserUtter:
    description: "用户输入动作"
    prompt: "..."
```

### 3. 策略配置错误

```yaml
# ❌ 错误：策略名称错误
policies:
  - name: unknown_policy

# ✅ 正确：使用支持的策略
policies:
  - name: trigger
  - name: rag
    llm: qwen-max
```

通过合理配置Agent，你可以创建功能强大、响应准确的COTA智能体。建议从基础配置开始，逐步添加复杂功能。
