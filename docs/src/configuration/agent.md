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
  use_proxy_user: false   # 是否启用代理用户模式
  max_proxy_step: 20      # 代理模式下的最大步骤数
  max_tokens: 500         # LLM生成最大令牌数
```

**配置参数**：

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `use_proxy_user` | ❌ | false | 是否启用代理用户功能，用于自动化模拟用户交互 |
| `max_proxy_step` | ❌ | 20 | 代理模式下的最大对话步数，防止无限循环 |
| `max_tokens` | ❌ | 500 | LLM生成的最大令牌数，控制回复长度 |

### 3. Policies配置 - 决策策略

**作用**：配置智能体的思维模式和决策策略，对应COTA的`DPL`(Dialogue Policy Learning)系统。

```yaml
policies:
  - type: trigger    # 触发式策略，基于规则快速响应
  - type: match      # 匹配策略，基于标注数据进行思维链学习
  - type: llm        # LLM策略，基于大模型推理 (三种策略中的一个或过个)
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
| `trigger` | `TriggerDPL` | 基于`policy/rules.yml`中定义的触发规则进行快速响应 |
| `match` | `MatchDPL` | 基于`policy/data.yml`中的标注数据学习思维链推理过程 |
| `llm` | `LLMDPL` | 基于大模型推理，支持动作级别的LLM绑定配置 |

**配置说明**：
- **trigger策略**：适用于简单、确定性的对话场景，响应速度快
- **match策略**：适用于复杂推理场景，通过学习标注数据生成思维链
- **llm策略**：基于大模型推理，支持为不同动作配置专用LLM
- **策略组合**：可以同时配置多种策略，系统会根据场景选择合适的策略

### 4. Knowledge配置 - 知识管理（可选）

**作用**：配置智能体的知识来源和检索策略，对应`Knowledge`和`KnowledgeFactory`类。主要用于RAG（检索增强生成）功能。

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
- **prompt**: 统一处理槽位更新和结果返回的主要提示词
- **slots**: 需要收集的信息槽位定义
- **executer**: 外部服务执行器

**配置示例**：
```yaml
Weather:  # 天气查询Form动作
  description: "查询天气"
  prompt: |
    当前正在执行{{current_form_name}}，其描述为{{current_form_description}}。
    根据对话内容及Action序列，结合当前slot的状态，填充或重置slot的值。
    
    历史Action序列为:
    {{history_actions_with_thoughts}}
    
    Action的描述为:
    {{action_descriptions}}
    
    当前slots为:
    {{current_form_slot_states}}
    
    slots的含义为:
    {{current_form_slot_descriptions}}
    
    填充或重置slot的值，保持slots格式输出json字符串。

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
        当前正在执行Action {{current_form_name}}, 其描述为 {{current_form_description}}。
        接下来需要询问用户，需要查询哪天的天气。

        你必须严格按照以下JSON格式响应：
        {"text": "<你的回复内容>"}

  executer:  # 执行器配置
    url: http://rap2api.taobao.org/app/mock/319677/Weather
    method: GET      # HTTP方法，可选GET、POST等
    output: ["<text>", "接口异常"]  # 预期输出格式
    mock: false      # 是否使用模拟数据
```

**Form动作工作流程**：
1. **槽位收集**：依次询问用户填充`slots`中定义的信息
2. **状态更新**：通过主`prompt`智能解析用户输入并更新槽位状态
3. **完整性检查**：当所有必需槽位填充完成后，进入执行阶段
4. **外部调用**：通过`executer`调用外部API获取结果
5. **结果返回**：返回执行结果给用户

**为什么要这样配置**：
- **prompt**: 统一处理槽位更新逻辑，简化配置结构
- **slots**: 结构化收集用户信息，避免信息遗漏
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
| `{{history_messages}}` | 历史消息列表 | UserUtter |
| `{{history_actions_with_thoughts}}` | 带思维链的历史动作序列 | BotUtter, Selector |
| `{{policies}}` | 策略思维链参考（来自policy/data.yml） | BotUtter, Selector |
| `{{action_descriptions}}` | 可用动作描述 | Selector |
| `{{current_form_name}}` | 当前表单名称 | Form动作 |
| `{{current_form_description}}` | 当前表单描述 | Form动作 |
| `{{current_form_slot_states}}` | 当前槽位状态 | Form动作 |
| `{{current_form_slot_descriptions}}` | 槽位描述信息 | Form动作 |
| `{{current_form_execute_result}}` | 执行结果 | Form动作执行后 |
| `{{knowledge}}` | 知识库检索结果 | BotUtter（当配置knowledge时） |

**重要说明**：
- `history_actions_with_thoughts` 包含完整的动作历史和思维过程，是推理的重要依据
- `policies` 变量提供标注数据作为思维链学习的参考模式

## 📚 推荐配置示例

### 1. 简单问答助手
```yaml
system:
  description: "你是一个智能问答助手，提供准确、有用的回答"

dialogue:
  use_proxy_user: false
  max_proxy_step: 20
  max_tokens: 300

policies:
  - type: trigger
  - type: match

actions:
  BotUtter:
    description: "回复用户"
    prompt: |
      你是一个智能助手，需要根据当前对话历史生成合适的回复。
      
      **任务描述：**
      {{task_description}}
      
      **输出格式要求：**
      ```json
      {"thought": "<你的推理过程>", "text": "<你的回复内容>"}
      ```
      
      **学习参考资料：**
      {{policies}}
      
      **实际对话历史：**
      {{history_actions_with_thoughts}}
      
  Selector:
    description: "选择动作"
    prompt: |
      你是一个智能对话助手，需要根据当前对话状态选择下一个最合适的Action。
      
      **输出格式要求：**
      ```json
      {"thought": "<你的推理过程>", "action": "<工具名称>"}
      ```
      
      **可用的Action工具：**
      {{action_descriptions}}
      
      **当前对话状态：**
      {{history_actions_with_thoughts}}
```

### 2. 带知识检索的客服助手
```yaml
system:
  description: "你是专业的客服助手，基于知识库提供准确服务"

dialogue:
  use_proxy_user: false
  max_proxy_step: 30
  max_tokens: 500

policies:
  - type: trigger
  - type: match

knowledge:
  - type: llm
    config:
      llms:
        - name: rag-glm-4
          action: BotUtter
        - name: rag-glm-4
          action: Selector
        - name: rag-glm-4  # 默认知识检索LLM

actions:
  BotUtter:
    description: "客服回复"
    prompt: |
      你是专业客服，需要提供准确、友好的服务。
      
      **任务描述：**
      {{task_description}}
      
      **输出格式要求：**
      ```json
      {"thought": "<你的分析过程>", "text": "<你的回复内容>"}
      ```
      
      **知识库信息：**
      {{knowledge}}
      
      **学习参考资料：**
      {{policies}}
      
      **实际对话历史：**
      {{history_actions_with_thoughts}}
      
  Selector:
    description: "动作选择器"
    prompt: |
      根据用户需求和知识库信息选择合适的响应动作。
      
      **可用动作：**
      {{action_descriptions}}
      
      **当前对话状态：**
      {{history_actions_with_thoughts}}
      
      **输出格式：**
      ```json
      {"thought": "<分析过程>", "action": "<动作名称>"}
      ```
```

### 3. 代理模式助手（自动化对话）
```yaml
system:
  description: "你是一个专业的宠物疾病问诊助手，擅长收集宠物症状信息并提供初步的诊断建议"

dialogue:
  use_proxy_user: true    # 启用代理模式
  max_proxy_step: 30
  max_tokens: 800

policies:
  - type: trigger
  - type: match

actions:
  UserUtter:              # 代理模式下必须配置UserUtter
    description: "用户的action - 宠物主人向问诊助手咨询宠物疾病"
    prompt: |
      你是一个关心宠物健康的主人，你的宠物可能出现了一些健康问题，你想要咨询专业的宠物问诊助手。
      
      **角色设定：**
      - 你是一个关心宠物的主人
      - 你会描述宠物的症状、行为变化等
      - 当得到满意的建议时，你会表示感谢并结束对话
      
      **历史对话：**
      {{history_messages}}
      
      **输出格式（严格按照JSON格式）：**
      ```json
      {
        "thought": "你的内心想法和推理过程",
        "text": "你作为宠物主人要说的话",
        "state": "continue/stop"
      }
      ```
      
  BotUtter:
    description: "专业宠物问诊助手回复用户"
    prompt: |
      你是一个专业的宠物疾病问诊助手，需要根据当前对话历史生成合适的回复。
      
      **输出格式要求：**
      ```json
      {"thought": "<你的推理过程>", "text": "<你的回复内容>"}
      ```
      
      **学习参考资料：**
      {{policies}}
      
      **实际对话历史：**
      {{history_actions_with_thoughts}}
      
  Selector:
    description: "选择合适的Actions"
    prompt: |
      你是一个专业的宠物问诊助手，需要根据当前对话状态选择下一个最合适的Action。
      
      **输出格式要求：**
      ```json
      {"thought": "<你的推理过程>", "action": "<工具名称>"}
      ```
      
      **可用的Action工具：**
      {{action_descriptions}}
      
      **当前对话状态：**
      {{history_actions_with_thoughts}}
```

通过合理配置Agent，可以创建功能强大、响应准确的COTA智能体。建议从简单配置开始，逐步增加复杂功能和Form动作。