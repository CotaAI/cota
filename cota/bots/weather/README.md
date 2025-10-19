# 天气查询机器人 (Weather Bot)

一个基于COTA框架的智能天气查询助手，展示了如何构建具有思维链推理能力的对话系统。

## 📁 项目结构

```
weather/
├── agent.yml          # 主要配置文件：系统描述、动作定义
├── endpoints.yml       # 端点配置：LLM和存储配置
├── policy/
│   ├── data.yml       # 思维链标注数据
│   └── rules.yml      # 触发规则配置
└── README.md          # 本文档
```

## ⚙️ 核心配置介绍

### 1. Agent配置 (agent.yml)

展示了COTA框架的核心配置元素：

#### 系统配置
```yaml
system:
  description: 你是一个智能助手，你需要认真负责的回答帮用户解决问题;要求回答的尽量精准和谨慎
```

#### 对话配置
```yaml
dialogue:
  use_proxy_user: false  # 非代理用户模式
  max_proxy_step: 30     # 最大对话轮次
  max_tokens: 500        # 最大生成token数
```

#### 策略配置
```yaml
policies:
  - type: trigger        # 基于规则的触发策略
  - type: match         # 基于匹配的思维链生成
```

#### 动作定义
```yaml
actions:
  BotUtter:      # 机器人回复动作
  Selector:      # 动作选择器
  Weather:       # 天气查询表单动作
  RenGong:       # 人工客服转接动作
```

### 2. LLM配置 (endpoints.yml) 

```yaml
llms:
  deepseek:
    type: openai
    model: deepseek-chat
    key: sk-xxx
    apibase: https://api.deepseek.com/v1
```

### 3. 思维链标注数据 (policy/data.yml)

提供了详细的思维过程标注，用于训练和指导模型的推理：

```yaml
- title: 复杂查天气
  actions:
    - name: UserUtter
      result: 成都和重庆天气咋样哪个好，我要看下去哪个城市旅游
    - name: Selector
      thought: 用户询问天气，同时问了成都和重庆天气，并让我做比较，我应该先执行Weather的到成都的天气，然后再执行Weather的到重庆的天气，然后比较
      result: Weather
```

## 🚀 快速开始

### 1. 启动机器人

```bash
cd /path/to/cota/bots/weather
cota shell --debug
```

### 2. 完整交互示例

以下是一个完整的对话会话，展示了COTA框架的Chain of Thought推理过程：

#### 会话概览
```
用户: 你好
机器人: 你好，请问有什么可以帮您？

用户: 我想查下天气  
机器人: 好的，我可以帮您查询天气。请告诉我您想查询哪个城市的天气？

用户: 杭州的
机器人: 请问您需要查询哪天的天气？

用户: 今天的
机器人: 杭州今天的天气是晴天。

用户: 帮我查下杭州和上海的天气,我看下去哪里旅游
机器人: 杭州和上海今天的天气都是晴天。如果您需要更多信息来帮助决定旅游目的地，请告诉我。
```

#### Chain of Thought 推理过程详解

**第1轮 - 打招呼**
```json
{
  "action": "Selector",
  "thought": "用户已打招呼，根据决策参考模式中的打招呼示例，我应该回复用户以继续对话。",
  "result": "BotUtter"
}
```

**第2轮 - 天气查询请求**
```json
{
  "action": "Selector", 
  "thought": "用户已打招呼并请求查询天气，根据决策参考模式中的复杂查天气示例，当用户询问天气时，应使用Weather工具查询。当前用户未指定城市和时间，因此需要先询问用户以获取必要参数。",
  "result": "BotUtter"
}
```

**第3轮 - 城市信息收集**
```json
{
  "action": "Selector",
  "thought": "用户已指定查询杭州的天气，根据决策参考模式中的复杂查天气示例，当用户提供城市信息时，应使用Weather工具查询天气。当前用户未指定时间，但Weather工具的时间参数是可选的，因此可以直接执行Weather工具查询杭州的天气。",
  "result": "Weather"
}
```

**第4轮 - 时间信息收集**
```json
{
  "action": "Weather",
  "slots": {"city": "杭州", "time": ""},
  "state": "start",
  "next_action": "BotUtter 请问您需要查询哪天的天气？"
}
```

**第5轮 - 执行查询**
```json
{
  "action": "Selector",
  "thought": "用户已指定查询杭州今天的天气，所有必要参数（城市和时间）已提供。根据决策参考模式中的复杂查天气示例，当用户提供完整天气查询信息时，应使用Weather工具执行查询。",
  "result": "Weather"
}
```

```json
{
  "action": "Weather",
  "slots": {"city": "杭州", "time": "今天"},
  "state": "end", 
  "result": "sunny"
}
```

**第6轮 - 复杂多城市查询**
```json
{
  "action": "Selector",
  "thought": "用户请求查询杭州和上海的天气以帮助决定旅游目的地，这类似于决策参考模式中的复杂查天气示例，其中用户询问多个城市天气并做比较。Weather工具只支持单个城市查询，因此需要先查询杭州的天气，然后查询上海的天气，最后比较结果回复用户。当前对话历史中，杭州天气已查询（结果为'sunny'），但上海天气未查询，因此下一个Action应使用Weather工具查询上海的天气。",
  "result": "Weather"
}
```

```json
{
  "action": "Weather", 
  "slots": {"city": "上海", "time": "今天"},
  "state": "end",
  "result": "sunny"
}
```

**最终回复生成**
```json
{
  "action": "Selector",
  "thought": "用户请求查询杭州和上海的天气以帮助决定旅游目的地，这类似于决策参考模式中的复杂查天气示例。Weather工具只支持单个城市查询，当前对话历史中已查询杭州天气（结果为'sunny'），并刚执行Weather工具查询上海天气（结果为'sunny'）。根据决策参考模式，在获取多个城市天气结果后，应使用BotUtter工具回复用户，提供天气比较结果并继续对话。",
  "result": "BotUtter"
}
```

## 📝 总结

这个天气机器人示例完整展示了COTA框架的核心能力：
- **基础配置**：展示了agent、llm、policy的完整配置方法
- **思维链推理**：每个决策都有明确的推理过程，提供完全可解释的AI对话
- **复杂任务处理**：能够将多步骤任务智能分解并逐步执行
- **实战应用**：基于真实对话数据，展示框架在实际场景中的表现

通过学习这个示例，您可以快速掌握COTA框架的使用方法，并构建属于自己的智能对话系统。
