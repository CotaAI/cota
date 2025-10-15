# Agent配置详解

Agent配置文件(`agent.yml`)是COTA智能体的核心配置文件，定义了智能体的身份、对话策略、知识管理和动作能力。它是智能体的"大脑"，决定了智能体如何思考、决策和响应用户。

## 🎯 Agent配置的作用与角色

**核心作用**：
- **身份定义**：通过`system`配置智能体的角色和性格
- **对话控制**：通过`dialogue`控制对话流程和参数
- **策略管理**：通过`policies`定义智能体的思维和决策模式
- **知识整合**：通过`knowledge`配置知识来源和检索策略
- **能力扩展**：通过`actions`定义智能体可执行的具体动作

**在COTA架构中的角色**：
- 被`Agent`类加载并解析为智能体实例
- 与`endpoints.yml`协同工作，前者定义能力，后者提供服务连接
- 通过`Processor`类驱动整体对话流程

## 📋 配置项总览

```yaml
system:      # 智能体身份 - 定义角色和基本信息
dialogue:    # 对话控制 - 控制对话模式和参数限制  
policies:    # 决策策略 - 定义思维模式和决策逻辑
knowledge:   # 知识管理 - 配置知识来源和检索策略
actions:     # 动作定义 - 定义智能体的具体能力和行为
```

| 配置项 | 对应模块 | 核心作用 |
|--------|----------|----------|
| `system` | `Agent`类初始化 | 设定智能体身份和描述 |
| `dialogue` | `Processor`对话处理 | 控制对话流程和限制 |
| `policies` | `DPL`策略学习 | 驱动智能体思考和决策 |
| `knowledge` | `Knowledge`知识管理 | 提供外部知识支持 |
| `actions` | `Action`系统 | 定义智能体的具体行为 |

## 🔧 详细配置说明

### 1. System配置 - 智能体身份

**作用**：定义智能体的基本身份信息，影响所有后续交互的语调和行为风格。

```yaml
system:
  description: "你是一个智能助手，你需要认真负责的回答帮用户解决问题"
  name: "assistant"  # 可选
```

**配置参数**：

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `description` | ✅ | - | 智能体角色描述，作为系统提示词的基础 |
| `name` | ❌ | "agent" | 智能体名称，用于日志和多Agent场景 |

### 2. Dialogue配置 - 对话控制

**作用**：控制对话的基本参数和流程限制，对应`Processor`类的对话处理逻辑。

```yaml
dialogue:
  mode: agent                    # 对话模式
  max_bot_step: 20              # 最大机器人执行步数
  use_proxy_user: false         # 是否启用代理用户模式
  max_proxy_user_step: 20       # 代理用户最大步数
  use_proxy_user_breaker: true  # 是否使用代理用户中断器
  max_tokens: 500               # LLM生成最大令牌数
```

**配置参数**：

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `mode` | ✅ | "agent" | 对话模式，当前支持"agent" |
| `max_bot_step` | ❌ | 10 | 单轮对话中机器人最大执行步数，防止无限循环 |
| `use_proxy_user` | ❌ | false | 是否启用代理用户功能，用于模拟用户交互 |
| `max_proxy_user_step` | ❌ | 10 | 代理用户模式下的最大步数限制 |
| `use_proxy_user_breaker` | ❌ | true | 是否使用中断器判断代理用户会话结束 |
| `max_tokens` | ❌ | 500 | LLM生成的最大令牌数，控制响应长度 |

### 3. Policies配置 - 决策策略

**作用**：配置智能体的思维模式和决策策略，对应COTA的`DPL`(Dialogue Policy Learning)系统。

```yaml
policies:
  - type: trigger              # 触发式策略，基于规则匹配
  - type: llm                 # LLM策略，基于大模型推理
    config:
      llms:                   # LLM配置列表
        - name: rag-glm-4    # 默认LLM
        - name: rag-utter    # BotUtter动作专用LLM
          action: BotUtter
        - name: rag-selector  # Selector动作专用LLM
          action: Selector
```

**策略类型说明**：

| 策略类型 | 对应类 | 作用机制 |
|----------|--------|----------|
| `trigger` | `TriggerDPL` | 基于历史动作序列模式匹配，预测下一步动作 |
| `llm` | `LLMDPL` | 使用LLM进行推理，生成思维链和动作决策 |

**LLM策略配置详解**：
- **默认模式**：未指定`action`的LLM作为默认模型
- **动作绑定**：通过`action`字段为特定动作类型绑定专用LLM
- **优先级**：动作绑定的LLM优先级高于默认LLM

### 4. Knowledge配置 - 知识管理

**作用**：配置智能体的知识来源和检索策略，对应`Knowledge`和`KnowledgeFactory`类。

```yaml
knowledge:
  - type: llm                 # LLM类型知识源
    config:
      llms: 
        - name: rag-glm-4    # 知识检索使用的LLM
          action: BotUtter   # 绑定到BotUtter动作
        - name: rag-glm-4
          action: Selector   # 绑定到Selector动作
        - name: rag-glm-4    # 默认知识LLM
```

**知识配置参数**：

| 参数 | 说明 |
|------|------|
| `type` | 知识源类型，当前支持"llm" |
| `config.llms` | 知识检索使用的LLM配置列表 |

### 5. Actions配置 - 动作定义

**作用**：定义智能体可执行的具体动作，每个动作对应一个`Action`类或其子类。

#### 5.1 基础动作

**UserUtter - 用户输入处理**
```yaml
UserUtter:
  description: "用户的action - 用户向智能体提问"
  prompt: |
    历史对话:
    {{history_messages}}
    请输出对医生说的话
    
  breaker:  # 对话中断判断器
    description: "判断是否跳出"
    prompt: |
      根据对话内容，判断对话是否满足要求
      对话内容: {{history_messages}}
      如果对话完整且可以结束, 输出标识符true。
      如果对话还需要继续, 输出标识符false。
      输出格式为: <标识符>
```

**BotUtter - 智能体回复**
```yaml
BotUtter:
  description: "回复用户"
  prompt: |
    你是一个智能助手，需要根据当前对话历史生成合适的回复。
    
    **任务描述：** {{task_description}}
    **输出格式要求：**
    你必须严格按照以下JSON格式响应，不要有任何其他内容：
    ```json
    {"thought": "<你的推理过程>", "text": "<你的回复内容>"}
    ```
    
    **学习参考资料：** {{policies}}
    **实际对话历史：** {{history_actions}}
    
    请分析上述实际对话历史，参考学习资料中的思维模式，生成合适的JSON格式回复：
```

**Selector - 动作选择器**
```yaml
Selector:
  description: "选择合适的Actions"
  prompt: |
    你是一个智能对话助手，需要根据当前对话状态选择下一个最合适的Action。
    
    **输出格式要求：**
    ```json
    {"thought": "<你的推理过程>", "action": "<工具名称>"}
    ```
    
    **可用的Action工具：** {{action_descriptions}}
    **决策参考模式：** {{policies}}
    **当前对话状态：** {{history_actions}}
    
    请分析当前对话状态，参考决策模式，选择最合适的下一个Action并输出JSON格式结果：
```

#### 5.2 Form动作 - 表单处理

**作用**：Form动作用于收集用户信息并执行外部API调用，对应`Form`类。

**核心组件**：
- **slots**: 需要收集的信息槽位
- **updater**: 槽位状态更新器
- **executer**: 外部服务执行器

**配置示例**：
```yaml
Weather:  # 天气查询Form动作
  description: "查询天气"
  prompt: |
    当前正在执行{{current_form_name}}, 其描述为{{current_form_description}}，将结果返给用户。
    结果为: {{current_form_execute_result}}
    你必须严格按照以下JSON格式响应：
    {"text": "<你的回复内容>"}

  updater:  # 槽位更新器（可选，有默认实现）
    description: "更新状态"
    prompt: |
      当前正在执行{{current_form_name}}，其描述为{{current_form_description}}。
      根据对话内容及Action序列，结合当前slot的状态，填充或重置slot的值。
      
      历史Action序列为: {{history_actions_with_thoughts}}
      Action的描述为: {{action_descriptions}}
      当前slots为: {{current_form_slot_states}}
      slots的含义为: {{current_form_slot_descriptions}}
      
      填充或重置slot的值, 保持slots格式输出json字符串。

  slots:  # 槽位定义
    city:
      description: "城市，注意：接口只支持输入单个城市"
      prompt: |
        当前正在执行Action {{current_form_name}}, 其描述为 {{current_form_description}}。
        接下来需要询问用户，需要查询哪个城市的天气。
        你必须严格按照以下JSON格式响应：
        {"text": "<你的回复内容>"}

    time:
      description: "时间"
      prompt: |
        需要询问用户，需要查询哪天的天气。
        {"text": "<你的回复内容>"}

  executer:  # 执行器配置
    url: http://rap2api.taobao.org/app/mock/319677/Weather
    method: GET      # HTTP方法，可选GET、POST等
    output: ["<text>", "接口异常"]  # 预期输出格式
    mock: false      # 是否使用模拟数据
```

**Form动作工作流程**：
1. **槽位收集**：依次询问用户填充`slots`中定义的信息
2. **状态更新**：通过`updater`解析用户输入并更新槽位状态
3. **完整性检查**：当所有必需槽位填充完成后，进入执行阶段
4. **外部调用**：通过`executer`调用外部API获取结果
5. **结果返回**：使用主`prompt`将执行结果返回给用户

**为什么要这样配置**：
- **slots**: 结构化收集用户信息，避免信息遗漏
- **updater**: 智能解析用户自然语言输入，提取结构化信息
- **executer**: 标准化外部服务调用，支持HTTP、模拟等多种方式

**配了可以做什么**：
- 实现结构化信息收集（如订单、预约、查询等）
- 集成外部API服务（天气、计算、数据库等）
- 提供交互式任务执行能力

#### 5.3 模板变量

所有Action的`prompt`支持丰富的模板变量：

| 变量名 | 说明 | 适用动作 |
|--------|------|----------|
| `{{task_description}}` | 任务描述 | 所有动作 |
| `{{history_messages}}` | 历史消息列表 | UserUtter, BotUtter |
| `{{history_actions}}` | 历史动作序列 | Selector, BotUtter |
| `{{policies}}` | 策略思维链参考 | BotUtter, Selector |
| `{{action_descriptions}}` | 可用动作描述 | Selector |
| `{{current_form_name}}` | 当前表单名称 | Form动作 |
| `{{current_form_slot_states}}` | 当前槽位状态 | Form动作 |
| `{{current_form_execute_result}}` | 执行结果 | Form动作 |

## 📚 推荐配置示例

### 1. 简单问答助手
```yaml
system:
  description: "你是一个智能问答助手，提供准确、有用的回答"

dialogue:
  mode: agent
  max_bot_step: 10
  max_tokens: 300

policies:
  - type: trigger
  - type: llm
    config:
      llms:
        - name: qwen-max

actions:
  UserUtter:
    description: "用户提问"
    prompt: "用户说：{{history_messages}}"
    
  BotUtter:
    description: "回复用户"
    prompt: |
      任务：{{task_description}}
      历史对话：{{history_actions}}
      输出格式：{"thought": "<思考>", "text": "<回复>"}
      
  Selector:
    description: "选择动作"
    prompt: |
      可用动作：{{action_descriptions}}
      当前状态：{{history_actions}}
      输出格式：{"thought": "<分析>", "action": "<动作名>"}
```

### 2. 带知识检索的客服助手
```yaml
system:
  description: "你是专业的客服助手，基于知识库提供准确服务"

dialogue:
  mode: agent
  max_bot_step: 15
  max_tokens: 500

policies:
  - type: trigger
  - type: llm
    config:
      llms:
        - name: rag-glm-4      # 使用RAG模型

knowledge:
  - type: llm
    config:
      llms:
        - name: rag-glm-4
          action: BotUtter
        - name: rag-glm-4
          action: Selector
        - name: rag-glm-4

actions:
  UserUtter:
    description: "用户咨询"
    prompt: "用户咨询：{{history_messages}}"
    
  RAG:
    description: "检索知识库回答"
    prompt: |
      根据检索内容回答用户问题
      检索内容：{{rag}}
      用户问题：{{history_messages}}
      请基于检索内容准确回答
      
  BotUtter:
    description: "客服回复"
    prompt: |
      你是专业客服，需要提供准确、友好的服务
      历史对话：{{history_actions}}
      参考资料：{{policies}}
      输出格式：{"thought": "<分析>", "text": "<回复>"}
```

### 3. 多功能服务助手（含Form动作）
```yaml
system:
  description: "你是全能服务助手，可以查询天气、进行计算等"

dialogue:
  mode: agent
  max_bot_step: 20
  max_tokens: 400

policies:
  - type: trigger
  - type: llm
    config:
      llms:
        - name: qwen-max
        - name: deepseek-chat
          action: Selector

actions:
  UserUtter:
    description: "用户请求"
    prompt: "用户说：{{history_messages}}"
    
  BotUtter:
    description: "助手回复"
    prompt: |
      任务：{{task_description}}
      历史：{{history_actions}}
      参考：{{policies}}
      格式：{"thought": "<思考>", "text": "<回复>"}
      
  Selector:
    description: "功能选择"
    prompt: |
      根据用户需求选择合适的功能：
      可用功能：{{action_descriptions}}
      对话历史：{{history_actions}}
      输出：{"thought": "<分析>", "action": "<功能>"}
      
  Weather:
    description: "天气查询"
    prompt: |
      查询结果：{{current_form_execute_result}}
      输出：{"text": "<天气信息>"}
    slots:
      city:
        description: "城市名称"
        prompt: '{"text": "请问您要查询哪个城市的天气？"}'
    executer:
      url: "https://api.weather.com/v1/current"
      method: GET
      mock: false
      
  Calculate:
    description: "数学计算"
    prompt: |
      计算结果：{{current_form_execute_result}}
      输出：{"text": "<计算结果>"}
    slots:
      expression:
        description: "数学表达式"
        prompt: '{"text": "请输入要计算的表达式："}'
    executer:
      url: "https://calc.api.com/calculate"
      method: POST
      mock: true
      output: ["<text>", "计算错误"]
```

通过合理配置Agent，可以创建功能强大、响应准确的COTA智能体。建议从简单配置开始，逐步增加复杂功能和Form动作。