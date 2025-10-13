# Policy配置详解

Policy配置文件(`policy/data.yml`)定义了智能体的对话策略和行为模式。它包含完整的对话流程示例，用于训练智能体理解对话模式、生成思维链和选择合适的动作。

## 📋 配置文件结构

```yaml
policies:                    # 策略列表
  - title: "策略标题"        # 策略名称
    actions:                 # 动作序列
      - name: ActionName     # 动作名称
        result: "结果"       # 执行结果
        thought: "思考过程"  # 思维链（可选）
      - name: NextAction
        result: "下一个结果"
```

## 🎯 Policy的作用

### 1. 对话模式学习
Policy提供完整的对话流程示例，帮助智能体：
- 理解用户意图和合适的响应
- 学习动作选择的逻辑
- 掌握对话的节奏和流程

### 2. 思维链生成
通过`thought`字段，Policy为智能体提供：
- 推理过程的参考
- 决策依据的示例
- 思考模式的模板

### 3. 动作序列指导
Policy展示了完整的动作序列：
- 从用户输入到系统响应的完整流程
- 不同场景下的处理方式
- 复杂任务的分解方法

## 📝 详细配置说明

### 基本Policy结构

```yaml
policies:
  - title: "打招呼"              # 策略标题，用于标识和调试
    actions:                     # 动作序列列表
      - name: UserUtter          # 用户输入动作
        result: "你好"           # 用户说的话
        
      - name: Selector           # 动作选择器
        thought: "用户打招呼，我应该礼貌回复"  # 选择理由
        result: BotUtter         # 选择的动作
        
      - name: BotUtter          # 机器人回复动作
        thought: "我需要友好地回应用户的问候"  # 回复思考
        result: "你好！很高兴为您服务，有什么可以帮助您的吗？"
```

### 字段说明

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `title` | string | ✅ | 策略标题，用于识别和调试 |
| `actions` | array | ✅ | 动作序列列表 |
| `name` | string | ✅ | 动作名称，必须在agent.yml中定义 |
| `result` | string/array | ✅ | 动作执行结果 |
| `thought` | string | ❌ | 思维链，推理过程描述 |

## 🎨 常见Policy模式

### 1. 简单问答模式

```yaml
policies:
  - title: "基础问答"
    actions:
      - name: UserUtter
        result: "你是谁？"
        
      - name: Selector
        thought: "用户询问我的身份，应该介绍自己"
        result: BotUtter
        
      - name: BotUtter
        thought: "需要简洁地介绍自己的身份和能力"
        result: "我是智能助手，可以帮助您解答问题和处理任务"
```

### 2. 多轮对话模式

```yaml
policies:
  - title: "天气查询对话"
    actions:
      - name: UserUtter
        result: "今天天气怎么样？"
        
      - name: Selector
        thought: "用户询问天气，但没有指定城市，需要先询问城市"
        result: Weather
        
      - name: Weather  # 第一次调用，会询问城市信息
        result: "请问您想查询哪个城市的天气？"
        
      - name: UserUtter
        result: "北京"
        
      - name: Weather  # 第二次调用，提供天气信息
        result: "北京今天多云，气温18-25°C，适合出行"
        
      - name: Selector
        thought: "已获取天气信息，应该告知用户"
        result: BotUtter
        
      - name: BotUtter
        thought: "需要完整地报告天气情况"
        result: "北京今天多云，气温18-25°C，天气不错，适合出行哦！"
```

### 3. 复杂任务处理模式

```yaml
policies:
  - title: "复杂查天气"
    actions:
      - name: UserUtter
        result: "成都和重庆天气咋样哪个好，我要看下去哪个城市旅游"
        
      - name: Selector
        thought: "用户询问两个城市的天气对比，需要分别查询然后比较"
        result: Weather
        
      - name: Weather
        result: "成都今天晴天，气温20-28°C"
        
      - name: Selector
        thought: "获得成都天气，还需要查询重庆天气"
        result: Weather
        
      - name: Weather
        result: "重庆今天多云转阴，气温22-30°C"
        
      - name: Selector
        thought: "两个城市天气都获取了，需要综合分析并给出建议"
        result: BotUtter
        
      - name: BotUtter
        thought: "需要对比两个城市的天气情况，给出旅游建议"
        result: "成都今天晴天20-28°C，重庆多云转阴22-30°C。从天气角度看，成都更适合旅游，阳光明媚视野好，更适合拍照和户外活动。"
```

### 4. 错误处理模式

```yaml
policies:
  - title: "接口异常处理"
    actions:
      - name: UserUtter
        result: "查询明天北京天气"
        
      - name: Selector
        thought: "用户想查询天气，调用天气接口"
        result: Weather
        
      - name: Weather
        result: "接口异常"  # 模拟接口错误
        
      - name: Selector
        thought: "天气接口异常，需要向用户说明并提供替代方案"
        result: BotUtter
        
      - name: BotUtter
        thought: "需要礼貌地告知用户服务暂时不可用，并建议其他方式"
        result: "抱歉，天气服务暂时不可用。您可以稍后再试，或查看官方天气应用获取信息。"
```

## 🎭 高级Policy配置

### 1. 条件分支模式

```yaml
policies:
  - title: "智能客服分流"
    actions:
      - name: UserUtter
        result: 
          - "转人工"
          - "人工客服"
          - "投诉"
        
      - name: Selector
        thought: "用户要求转人工，检查是否满足转接条件"
        result: RenGong
        
      - name: RenGong
        result: "成功"
        
      - name: BotUtter
        thought: "转人工成功，需要告知用户等待时间"
        result: "正在为您转接人工客服，请稍候..."

  - title: "智能客服分流-失败"
    actions:
      - name: UserUtter
        result: "转人工"
        
      - name: Selector
        thought: "用户要求转人工"
        result: RenGong
        
      - name: RenGong
        result: "失败"  # 转接失败的情况
        
      - name: BotUtter
        thought: "转人工失败，需要提供替代方案"
        result: "抱歉，当前人工客服繁忙，建议您稍后再试或留下联系方式，我们会尽快回复。"
```

### 2. 多结果模式

Policy支持一个动作有多种可能的结果：

```yaml
policies:
  - title: "天气查询-多种表达"
    actions:
      - name: UserUtter
        result: 
          - "天气怎么样"
          - "今天天气如何"
          - "外面热不热"
          - "需要带伞吗"
        
      - name: Selector
        thought: "用户询问天气相关信息，需要查询天气"
        result: Weather
```

### 3. 上下文相关模式

```yaml
policies:
  - title: "基于历史的智能回复"
    actions:
      - name: UserUtter
        result: "我刚才问的那个问题"
        
      - name: Selector
        thought: "用户提到'刚才的问题'，需要从对话历史中理解上下文"
        result: BotUtter
        
      - name: BotUtter
        thought: "需要回顾对话历史，理解用户指的是哪个问题"
        result: "您刚才询问的是天气情况，我已经为您查询了相关信息。还有其他需要了解的吗？"
```

## 🔧 Policy优化策略

### 1. 覆盖性优化

确保Policy覆盖主要使用场景：

```yaml
# 覆盖不同的用户表达方式
policies:
  - title: "问候语-正式"
    actions:
      - name: UserUtter
        result: "您好，请问..."
      # ... 后续动作
      
  - title: "问候语-随意"
    actions:
      - name: UserUtter
        result: "嗨，我想..."
      # ... 后续动作
      
  - title: "问候语-简短"
    actions:
      - name: UserUtter
        result: "你好"
      # ... 后续动作
```

### 2. 思维链质量优化

提供高质量的thought示例：

```yaml
policies:
  - title: "高质量思维链示例"
    actions:
      - name: UserUtter
        result: "我的订单什么时候到？"
        
      - name: Selector
        thought: "用户询问订单状态，但没提供订单号。我需要先获取订单信息才能查询状态，所以应该询问订单号。"
        result: OrderQuery
        
      - name: OrderQuery
        thought: "为了准确查询订单状态，我需要用户提供具体的订单编号。"
        result: "请提供您的订单号，我来帮您查询配送状态。"
```

### 3. 分层策略设计

按复杂度分层设计Policy：

```yaml
# 第一层：基础交互
policies:
  - title: "基础-问候"
    actions: [...]
    
  - title: "基础-告别"
    actions: [...]

# 第二层：功能操作
  - title: "功能-查询天气"
    actions: [...]
    
  - title: "功能-设置提醒"
    actions: [...]

# 第三层：复杂业务
  - title: "复杂-多步骤查询"
    actions: [...]
    
  - title: "复杂-异常处理"
    actions: [...]
```

## 📊 Policy效果评估

### 1. 覆盖率指标

```yaml
# 在policy文件中添加元数据
metadata:
  coverage:
    user_intents: ["greeting", "query", "complaint", "farewell"]
    business_scenarios: ["normal", "error", "exception"]
    interaction_patterns: ["single_turn", "multi_turn", "context_dependent"]
```

### 2. 质量评估标准

- **完整性**：动作序列是否完整合理
- **逻辑性**：thought是否符合推理逻辑
- **多样性**：是否覆盖不同的表达方式
- **现实性**：是否符合真实对话场景

## 🚨 常见配置错误

### 1. 动作序列不完整

```yaml
# ❌ 错误：缺少后续处理
policies:
  - title: "不完整的序列"
    actions:
      - name: UserUtter
        result: "查询天气"
      - name: Selector
        result: Weather
      # 缺少Weather动作和后续处理

# ✅ 正确：完整的动作序列
policies:
  - title: "完整的天气查询"
    actions:
      - name: UserUtter
        result: "查询天气"
      - name: Selector
        thought: "用户要查询天气"
        result: Weather
      - name: Weather
        result: "今天晴天，25°C"
      - name: Selector
        thought: "获取到天气信息，告知用户"
        result: BotUtter
      - name: BotUtter
        result: "今天天气很好，晴天25°C，适合出行！"
```

### 2. 思维链质量差

```yaml
# ❌ 错误：思维链太简单
policies:
  - title: "低质量思维链"
    actions:
      - name: Selector
        thought: "选择动作"  # 过于简单，没有推理过程
        result: BotUtter

# ✅ 正确：高质量思维链
policies:
  - title: "高质量思维链"
    actions:
      - name: Selector
        thought: "用户询问天气但没指定城市，我需要先了解具体位置才能提供准确信息"
        result: Weather
```

### 3. 结果格式不一致

```yaml
# ❌ 错误：结果格式不一致
policies:
  - title: "格式不一致"
    actions:
      - name: UserUtter
        result: "你好"           # 字符串格式
      - name: UserUtter
        result: ["嗨", "hello"]  # 数组格式，但前面是字符串

# ✅ 正确：保持格式一致
policies:
  - title: "格式一致"
    actions:
      - name: UserUtter
        result: 
          - "你好"
          - "嗨"
          - "hello"
```

## 📚 Policy模板

### 基础对话模板

```yaml
policies:
  - title: "标准问答模板"
    # 描述：单轮问答的标准流程
    actions:
      - name: UserUtter
        result: "用户问题"
        
      - name: Selector
        thought: "分析用户意图，选择合适的处理方式"
        result: BotUtter
        
      - name: BotUtter
        thought: "根据问题提供准确的回答"
        result: "智能体回复"
```

### 服务查询模板

```yaml
policies:
  - title: "服务查询模板"
    # 描述：需要调用外部服务的查询流程
    actions:
      - name: UserUtter
        result: "查询请求"
        
      - name: Selector
        thought: "用户需要查询信息，调用相应服务"
        result: ServiceAction
        
      - name: ServiceAction
        result: "服务返回结果"
        
      - name: Selector
        thought: "获取到查询结果，整理后告知用户"
        result: BotUtter
        
      - name: BotUtter
        thought: "将查询结果以用户友好的方式呈现"
        result: "整理后的查询结果"
```

通过精心设计Policy配置，你可以让COTA智能体学习到丰富的对话模式和处理逻辑，从而提供更自然、更智能的对话体验。
