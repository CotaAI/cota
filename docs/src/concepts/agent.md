在多轮对话系统中，Agent 是一个核心组件，负责管理和执行对话流程。它通过与用户交互，理解用户意图，并根据预定义的规则和逻辑生成相应的响应。
Agent 的设计旨在确保对话的流畅性和准确性，从而提供良好的用户体验。

## Agent 的配置
Agent 的配置主要包括以下几个方面：

描述信息：提供 Agent 的基本描述，帮助开发者理解其用途和功能。
动作配置：定义 Agent 可以执行的动作，每个动作都有名称、描述、提示等信息。
对话配置：配置对话的流程和规则，确保对话按照预期进行。
存储配置：指定数据存储的方式，如内存存储或 SQL 数据库。
LLM 配置：配置与语言模型（LLM）的交互方式，确保 Agent 能够生成高质量的文本响应。

如下是一个简单的task.yml的配置，存储配置和LLM配置在endpoints.yml中
```yaml
description: 在本任务中,你是一名宠物医生，你需要认真负责的回答帮用户解决问题;要求回答的尽量精准和谨慎

actions:
  Query:
    description: "用户向智能体提问"
  Response:
    description: "回复用户的提问"
    prompt: |
      根据任务描述和历史对话，生成回答。

      任务描述:
      {{task_description}}

      历史对话:
      {{history_messages}}

      请回答用户

dialogue:
  mode: agent
  max_bot_step: 20
  use_proxy_user: false
  max_proxy_user_step: 20
  use_proxy_user_breaker: false    

```

## Agent 和其它模块的关系
Processor：Processor 是 Agent 的核心处理模块，负责处理对话的逻辑和状态更新。Agent 通过 Processor 与其它模块进行交互。
Store：Store 模块负责数据的存储和检索，Agent 通过 Store 模块保存和获取对话状态、用户数据等。
LLM：LLM 模块是语言模型接口，Agent 通过 LLM 生成文本响应，提供自然语言处理、对话状态跟踪 和 动作执行决策能力。
DST（Dialogue State Tracker）：DST 模块跟踪对话的状态，Agent 通过 DST 获取当前对话状态，确保对话的连贯性。
