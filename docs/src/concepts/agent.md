# Agent（智能体）

Agent是COTA框架中的核心组件，负责管理和执行对话流程。它通过与用户交互，理解用户意图，并根据预定义的规则和策略生成相应的响应。Agent的设计旨在确保对话的流畅性、准确性和智能化，从而提供良好的用户体验。

## 🎯 Agent的核心功能

Agent提供以下核心功能：

### 1. 对话管理
- **状态跟踪**: 通过DST（对话状态跟踪器）维护对话上下文
- **流程控制**: 管理对话的开始、进行和结束
- **多轮支持**: 支持复杂的多轮对话场景

### 2. 智能决策
- **动作选择**: 通过Selector智能选择下一步执行的动作
- **策略学习**: 基于DPL（对话策略学习）进行决策优化
- **思维链**: 支持Chain of Thought推理，提供可解释的决策过程

### 3. 知识集成
- **RAG支持**: 集成知识库进行检索增强生成
- **多模态**: 支持文本、图像等多种模态的处理
- **动态学习**: 在对话过程中动态学习和适应

## 🔧 Agent配置

Agent的配置主要包括以下几个方面：

- **系统描述**: 定义Agent的角色、性格和基本行为模式
- **对话配置**: 控制对话模式、参数限制和代理功能
- **策略配置**: 定义思维模式和决策策略（trigger、match、llm）
- **知识配置**: 配置知识来源和检索策略（可选）
- **动作配置**: 定义Agent可执行的具体动作和行为

配置文件结构如下：`agent.yml`（主要配置）+ `endpoints.yml`（服务连接配置）

**agent.yml配置示例**：
```yaml
system:
  description: "你是一名专业的宠物医生，需要认真负责地回答用户问题，要求回答的尽量精准和谨慎"

dialogue:
  use_proxy_user: false  # 是否启用代理用户模式
  max_proxy_step: 20     # 代理模式下的最大步骤数
  max_tokens: 500        # LLM生成的最大令牌数

policies:
  - type: trigger        # 基于规则的触发策略
  - type: match         # 基于标注数据的思维链学习

actions:
  BotUtter:
    description: "回复用户的提问"
    prompt: |
      你是一名专业的宠物医生，需要根据当前对话历史生成合适的回复。

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

      请分析上述对话历史，参考学习资料中的思维模式，生成专业的医疗建议。

  Selector:
    description: "选择合适的Actions"
    prompt: |
      你需要根据当前对话状态选择下一个最合适的Action。

      **可用的Action工具：**
      {{action_descriptions}}

      **当前对话状态：**
      {{history_actions_with_thoughts}}

      **输出格式：**
      ```json
      {"thought": "<你的分析过程>", "action": "<动作名称>"}
      ```
```

**endpoints.yml配置示例**：
```yaml
llms:
  deepseek:
    type: openai
    model: deepseek-chat
    key: your_api_key_here
    apibase: https://api.deepseek.com/v1

channel:
  type: redis
  host: localhost
  port: 6379
  db: 1

base_store:
  type: Memory
  # 或者使用SQL数据库
  # type: SQL
  # dialect: mysql+pymysql
  # host: localhost
  # port: 3306
  # db: cota_agent
  # username: your_username
  # password: your_password
```

## 🔄 Agent与其它模块的关系

Agent作为COTA框架的核心协调者，与各个模块密切协作：

### 核心模块交互
- **Processor**: Agent的核心处理引擎，负责对话逻辑和状态更新，是Agent与其他模块交互的中枢
- **DST（对话状态跟踪器）**: 维护对话状态，为Agent提供丰富的上下文信息和模板变量
- **DPL（对话策略学习）**: 为Agent提供智能决策能力，生成思维链和动作预测
- **Action系统**: Agent通过Action执行具体的对话行为，包括UserUtter、BotUtter、Selector等

### 外部服务集成
- **LLM**: 语言模型服务，为Agent提供自然语言理解和生成能力
- **Store**: 数据存储服务，持久化对话状态和用户数据
- **Channel**: 通信通道，连接Agent与外部用户或系统
- **Knowledge**: 知识库服务，为Agent提供外部知识支持（RAG）

### 架构关系图
```
User Input
    ↓
[Channel] ←→ [Agent] ←→ [Processor]
                ↓           ↓
            [Actions] ←→ [DST] ←→ [DPL]
                ↓           ↓      ↓
            [LLM] ←←←← [Store] → [Knowledge]
```

## 🚀 Agent运行流程

### 1. 初始化阶段
1. **配置加载**: 从`agent.yml`和`endpoints.yml`加载配置
2. **模块初始化**: 创建LLM、Store、Knowledge等服务实例
3. **Action注册**: 根据配置注册可用的Action
4. **策略加载**: 初始化DPL策略（trigger、match、llm）

### 2. 对话处理阶段
1. **消息接收**: 通过Channel接收用户消息
2. **状态跟踪**: DST更新对话状态，生成上下文变量
3. **策略决策**: DPL生成思维链，Selector选择下一个Action
4. **Action执行**: 执行选定的Action（BotUtter、Form等）
5. **响应生成**: 通过LLM生成响应内容
6. **状态保存**: Store持久化更新后的对话状态
7. **消息发送**: 通过Channel将响应发送给用户

### 3. 特殊功能
- **代理模式**: 启用`use_proxy_user`后，Agent可自动模拟用户输入
- **知识检索**: 配置Knowledge后，Agent可集成外部知识库
- **思维链**: 支持Chain of Thought，提供可解释的推理过程
- **多策略**: 同时支持规则、匹配和LLM多种决策策略

通过这种模块化设计，Agent能够灵活应对各种对话场景，从简单问答到复杂的多轮业务对话。
