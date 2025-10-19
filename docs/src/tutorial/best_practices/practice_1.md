# 实践1：构建智能天气查询机器人

> **学习目标**：掌握COTA框架的基础配置和Chain of Thought推理机制

这个实践将基于weather bot示例，带您从零开始构建一个具有思维链推理能力的天气查询机器人。

## 📋 项目概览

### 功能特性
- ✅ 智能天气查询（单城市/多城市对比）
- ✅ 思维链推理过程完全可视化
- ✅ 多轮对话状态管理
- ✅ 表单式信息收集
- ✅ 人工客服转接

### 技术亮点
- **Chain of Thought**: 每个决策都有明确的推理过程
- **状态管理**: 智能收集和管理对话状态
- **策略组合**: trigger + match双重策略保证响应质量

## 🏗️ 项目结构

```
weather/
├── agent.yml          # 智能体核心配置
├── endpoints.yml       # LLM和服务配置
├── policy/
│   ├── data.yml       # Chain of Thought标注数据
│   └── rules.yml      # 触发规则配置
└── README.md          # 文档说明
```

## ⚙️ 配置详解

### 1. 智能体配置 (agent.yml)

#### 系统描述
```yaml
system:
  description: 你是一个智能助手，你需要认真负责的回答帮用户解决问题;要求回答的尽量精准和谨慎
```

#### 对话配置
```yaml
dialogue:
  use_proxy_user: false  # 真实用户交互模式
  max_proxy_step: 30     # 最大对话轮次
  max_tokens: 500        # 控制回复长度
```

#### 策略配置
```yaml
policies:
  - type: trigger        # 基于规则的快速响应
  - type: match         # 基于标注的思维链推理
```

### 2. 核心动作定义

#### BotUtter - 智能回复动作
```yaml
BotUtter:
  description: "回复用户"
  prompt: |
    你是一个智能助手，需要根据当前对话历史生成合适的回复。
    
    **输出格式要求：**
    你必须严格按照以下JSON格式响应：
    ```json
    {"thought": "<你的推理过程>", "text": "<你的回复内容>"}
    ```
    
    **对话历史：**
    {{history_actions_with_thoughts}}
```

#### Selector - 动作选择器
```yaml
Selector:
  description: "选择合适的Actions"
  prompt: |
    你是一个智能对话助手，需要根据当前对话状态选择下一个最合适的Action。
    
    **输出格式：**
    ```json
    {"thought": "<你的推理过程>", "action": "<工具名称>"}
    ```
    
    **可用的Action工具：**
    {{action_descriptions}}
    
    **当前对话状态：**
    {{history_actions_with_thoughts}}
```

#### Weather - 天气查询表单
```yaml
Weather:
  description: "查询天气信息"
  slots:
    city:
      description: "用户询问的城市名称"
    time:
      description: "用户询问的时间（今天、明天等）"
  executer:
    type: script
    script: |
      # 模拟天气查询
      return {"text": "sunny", "metadata": {}}
```

### 3. LLM配置 (endpoints.yml)
```yaml
llms:
  deepseek:
    type: openai
    model: deepseek-chat
    key: your_api_key_here  # 请替换为真实API密钥
    apibase: https://api.deepseek.com/v1

channel:
  type: redis
  host: localhost
  port: 6379
  db: 1
```

## 🧠 Chain of Thought 核心机制

### 思维链标注数据 (policy/data.yml)

```yaml
policies:
- title: 复杂查天气  
  actions:
    - name: UserUtter
      result: 成都和重庆天气咋样哪个好，我要看下去哪个城市旅游
    - name: Selector
      thought: 用户询问天气，同时问了成都和重庆天气，并让我做比较，我应该先执行Weather得到成都的天气，然后再执行Weather得到重庆的天气，然后比较
      result: Weather
    - name: Weather
      slots:
        city: 成都
        time: 今天
      state: end
      result: 
        text: sunny
        metadata: {}
    - name: Selector  
      thought: 已经查询了成都天气，现在需要查询重庆天气进行对比
      result: Weather
    - name: Weather
      slots:
        city: 重庆  
        time: 今天
      state: end
      result:
        text: cloudy
        metadata: {}
    - name: Selector
      thought: 已获取成都(sunny)和重庆(cloudy)的天气，现在需要对比并给出旅游建议
      result: BotUtter
    - name: BotUtter
      result:
        text: 成都今天天气晴朗(sunny)，重庆今天是阴天(cloudy)。从天气角度来看，成都的天气更适合旅游活动。不过您也可以考虑其他因素如景点、美食等来做最终决定。
        thought: 对比两个城市天气后，成都天气更好，但也要提醒用户考虑其他旅游因素
```

## 🚀 实战演练

### 步骤1：环境准备
```bash
# 1. 进入示例目录
cd /path/to/cota/bots/weather

# 2. 配置API密钥
vim endpoints.yml
# 将your_api_key_here替换为实际的API密钥

# 3. 启动调试模式
cota shell --debug
```

### 步骤2：基础对话测试
```
用户输入: 你好
预期回复: 你好，请问有什么可以帮您？

用户输入: 我想查天气
预期回复: 好的，我可以帮您查询天气。请告诉我您想查询哪个城市的天气？
```

### 步骤3：复杂场景测试
```
用户输入: 帮我查下杭州和上海的天气，我看下去哪里旅游
系统行为: 
1. Selector识别需要查询两个城市天气
2. 先查询杭州天气
3. 再查询上海天气  
4. 对比结果并给出建议
```

## 📊 思维链可视化

每一步决策都包含完整的推理过程：

```json
{
  "action": "Selector",
  "thought": "用户请求查询杭州和上海的天气以帮助决定旅游目的地，这类似于决策参考模式中的复杂查天气示例，其中用户询问多个城市天气并做比较。Weather工具只支持单个城市查询，因此需要先查询上海的天气。",
  "result": "Weather"
}
```

这种透明的推理过程确保了：
- **可解释性**: 每个决策都有明确理由
- **可调试性**: 便于发现和修复逻辑问题  
- **可优化性**: 基于推理过程持续改进

## 🎯 最佳实践总结

### 1. 配置策略
- **渐进式配置**: 从简单trigger开始，逐步添加match策略
- **思维链标注**: 提供高质量的推理过程示例
- **错误处理**: 配置合适的fallback机制

### 2. 提示词工程
- **结构化输出**: 统一JSON格式确保解析稳定
- **上下文管理**: 合理使用`{{history_actions_with_thoughts}}`
- **角色定义**: 清晰的系统描述和动作描述

### 3. 调试技巧
- **调试模式**: 使用`--debug`查看完整推理过程
- **分步测试**: 从简单对话到复杂场景逐步验证
- **日志分析**: 关注thought字段定位问题

### 4. 生产部署
- **API密钥管理**: 使用环境变量保护敏感信息
- **持久化存储**: 配置Redis和数据库确保状态持久化
- **监控告警**: 设置appropriate的监控和日志

通过这个实践，您已经掌握了COTA框架的核心能力。接下来可以尝试实践2，学习更高级的代理模式功能。