# 标注数据配置详解

标注数据是COTA智能体的"学习材料"，通过提供带思维链的对话示例和触发规则，训练智能体学习对话策略、决策模式和自动响应机制。这些数据直接影响智能体的表现质量和交互能力。

## 🎯 标注数据的作用与价值

**核心价值**：
- **策略学习**：通过完整对话流程示例，让智能体学习复杂的对话处理策略
- **思维训练**：通过思维链标注，训练智能体的推理和决策能力
- **快速响应**：通过触发规则，实现对特定输入的即时准确响应
- **质量保证**：通过精心设计的标注数据，确保智能体输出的一致性和准确性

**对COTA运行的影响**：
- **DPL策略生成**：`DPL`系统根据标注数据生成思维链和动作预测
- **触发匹配**：`TriggerDPL`基于触发规则进行快速模式匹配
- **响应质量**：标注数据的质量直接决定智能体的回答质量
- **行为一致性**：规范化的标注确保智能体行为的可预测性

## 📁 配置文件位置

标注数据配置位于机器人项目的`policy/`目录下：

```
your_bot/                    # 机器人项目根目录
├── agent.yml              # 智能体配置
├── endpoints.yml           # 服务连接配置
└── policy/                 # 标注数据目录 ⭐
    ├── data.yml           # 对话策略数据（Policy配置）
    ├── rules.yml          # 触发规则数据（Trigger配置）  
    └── *.md               # RAG知识库文件（可选）
```

**加载机制**：
- `Agent.load_from_path()`方法会自动扫描`policy/`目录
- `DPLFactory.create()`负责加载和解析标注数据
- `MatchDPL`和`TriggerDPL`分别处理策略数据和触发规则

## 📋 配置项概览

| 配置文件 | 对应组件 | 主要作用 | 数据格式 |
|----------|----------|----------|----------|
| `policy/data.yml` | `MatchDPL` | 对话策略学习，生成思维链 | 完整对话流程+思考过程 |
| `policy/rules.yml` | `TriggerDPL` | 快速触发响应，精确匹配 | 关键词匹配+预定义动作 |

## 🧠 Policy配置 - 对话策略学习数据

**作用**：提供完整的对话流程示例，训练智能体的推理能力和对话策略。

### 配置结构

```yaml
# policy/data.yml
policies:                    # 策略数据列表
  - title: "策略标题"        # 策略名称，用于识别
    actions:                 # 完整动作序列
      - name: UserUtter      # 用户输入动作
        result: "用户说的话"  # 用户输入内容
      - name: Selector       # 动作选择器  
        thought: "选择理由"   # 思维链：为什么选择这个动作
        result: BotUtter     # 选择的动作名
      - name: BotUtter       # 机器人回复动作
        thought: "回复思考"   # 思维链：如何生成回复
        result: "回复内容"    # 实际回复内容
```

### Policy数据类型

#### 1. 基础问答策略
```yaml
policies:
  - title: "简单问答"
    actions:
      - name: UserUtter
        result: "你是谁？"
        
      - name: Selector
        thought: "用户询问身份，我应该简洁地介绍自己的角色和能力"
        result: BotUtter
        
      - name: BotUtter
        thought: "需要友好地介绍自己，让用户了解我能提供什么帮助"
        result: "我是智能助手，可以帮助您解答问题、查询信息和处理各种任务。"
```

#### 2. 多轮对话策略
```yaml
policies:
  - title: "天气查询多轮对话"
    actions:
      - name: UserUtter
        result: "今天天气怎么样？"
        
      - name: Selector
        thought: "用户询问天气，但没有指定城市，需要先获取位置信息"
        result: Weather
        
      - name: Weather  # Form动作第一次执行，询问缺失信息
        result: "请问您想查询哪个城市的天气？"
        
      - name: UserUtter
        result: "北京"
        
      - name: Weather  # Form动作第二次执行，返回查询结果
        result: "北京今天多云，气温18-25°C"
        
      - name: Selector
        thought: "已获取天气信息，需要以用户友好的方式告知结果"
        result: BotUtter
        
      - name: BotUtter
        thought: "整合天气信息，提供完整有用的回复"
        result: "北京今天多云，气温18-25°C，天气不错，适合出行！记得适当增减衣物。"
```

#### 3. 复杂业务策略
```yaml
policies:
  - title: "订单查询处理"
    actions:
      - name: UserUtter
        result: "我的订单什么时候到？"
        
      - name: Selector
        thought: "用户询问订单状态，但没提供订单号，需要先获取订单信息"
        result: OrderQuery
        
      - name: OrderQuery
        result: "请提供您的订单号，我来帮您查询配送状态"
        
      - name: UserUtter
        result: "订单号：202310151234"
        
      - name: OrderQuery  # 执行订单查询
        result: "订单202310151234正在配送中，预计明天下午送达"
        
      - name: Selector
        thought: "已获取订单信息，需要详细告知用户配送情况"
        result: BotUtter
        
      - name: BotUtter
        thought: "提供完整的订单状态信息，包括配送进度和预计时间"
        result: "您的订单202310151234正在配送中，预计明天下午送达。配送员会提前联系您，请保持手机畅通。"
```

### Policy配置要点

**思维链设计原则**：
- **具体化**：描述具体的推理过程，而非简单的结论
- **逻辑性**：体现清晰的因果关系和决策依据  
- **一致性**：保持思维模式的统一性
- **实用性**：贴近真实的对话处理场景

**动作序列设计**：
- **完整性**：从用户输入到最终回复的完整流程
- **真实性**：模拟真实的人机对话场景
- **多样性**：覆盖不同的对话模式和处理方式

## ⚡ Trigger配置 - 触发规则数据

**作用**：定义关键词触发规则，实现对特定输入的快速精确响应。

### 配置结构

```yaml
# policy/rules.yml
triggers:                    # 触发规则列表
  - title: "规则标题"        # 触发规则名称
    actions:                 # 触发的动作序列
      - name: UserUtter      # 用户输入匹配
        result:              # 匹配的关键词列表
          - "关键词1"
          - "关键词2"
      - name: ActionName     # 触发执行的动作
        result: "预期结果"   # 预期的执行结果
```

### Trigger规则类型

#### 1. 服务转接类
```yaml
triggers:
  - title: "转人工客服"
    actions:
      - name: UserUtter
        result:
          - "转人工"
          - "人工客服"
          - "真人服务"
          - "客服专员"
          - "manual service"
          - "human agent"
      - name: TransferToHuman
        result: "正在为您转接人工客服，请稍候..."

  - title: "技术支持转接"
    actions:
      - name: UserUtter
        result:
          - "技术支持"
          - "技术问题"
          - "bug反馈"
          - "系统故障"
          - "technical support"
      - name: TransferToTech
        result: "正在为您转接技术支持专家..."
```

#### 2. 业务操作类
```yaml
triggers:
  - title: "退款申请"
    actions:
      - name: UserUtter
        result:
          - "退款"
          - "退钱"
          - "申请退款"
          - "我要退款"
          - "refund"
      - name: RefundProcess
        result: "已为您启动退款流程，请稍后填写退款信息"

  - title: "订单查询"
    actions:
      - name: UserUtter
        result:
          - "查订单"
          - "订单状态"
          - "我的订单"
          - "订单查询"
          - "order status"
      - name: OrderQuery
        result: "请提供您的订单号，我来帮您查询"
```

#### 3. 紧急处理类
```yaml
triggers:
  - title: "紧急情况处理"
    actions:
      - name: UserUtter
        result:
          - "紧急"
          - "urgent"
          - "emergency"
          - "很急"
          - "马上处理"
      - name: UrgentHandler
        result: "已标记为紧急事件，将优先为您处理"

  - title: "投诉升级"
    actions:
      - name: UserUtter
        result:
          - "投诉"
          - "complaint"
          - "不满意"
          - "差评"
          - "要投诉"
      - name: ComplaintEscalation
        result: "您的意见很重要，已升级至客服主管处理"
```

### Trigger配置要点

**关键词选择原则**：
- **准确性**：确保关键词能准确表达用户意图
- **覆盖性**：包含同义词、近义词和常见表达
- **排他性**：避免与其他规则产生冲突
- **多语言**：根据需要支持多语言关键词

**匹配策略**：
- **精确匹配**：用户输入完全等于关键词
- **包含匹配**：用户输入包含关键词
- **优先级控制**：通过规则顺序控制匹配优先级

## 🔄 Policy与Trigger协同工作

### 工作机制
1. **Trigger优先**：系统首先检查是否有触发规则匹配
2. **Policy补充**：未匹配触发规则时，使用Policy数据进行策略推理
3. **思维融合**：Policy的思维链为所有动作提供推理参考

### 数据协同设计
```yaml
# policy/rules.yml - 快速响应
triggers:
  - title: "快速退款"
    actions:
      - name: UserUtter
        result: ["我要退款"]
      - name: RefundProcess
        result: "启动退款"

# policy/data.yml - 详细处理流程  
policies:
  - title: "退款详细流程"
    actions:
      - name: UserUtter
        result: "退款遇到问题怎么办？"
      - name: Selector
        thought: "用户在退款过程中遇到问题，需要提供详细的解决方案和后续流程指导"
        result: BotUtter
      - name: BotUtter
        thought: "提供全面的退款问题解决方案，包括常见问题和联系方式"
        result: "退款遇到问题时，您可以：1)检查银行卡信息是否正确 2)等待3-5个工作日 3)联系客服核实状态。如需进一步帮助，我可以为您转接专人处理。"
```

## 🎨 数据标注最佳实践

### 1. 分层数据设计
```yaml
# 第一层：基础交互（高频场景）
policies:
  - title: "基础-问候"
  - title: "基础-告别"
  - title: "基础-感谢"

# 第二层：功能操作（核心业务）
policies:
  - title: "功能-天气查询"
  - title: "功能-订单查询"
  - title: "功能-信息修改"

# 第三层：复杂处理（异常情况）
policies:
  - title: "复杂-多条件查询"
  - title: "复杂-异常处理"
  - title: "复杂-升级转接"
```

### 2. 思维链质量标准
```yaml
# ✅ 高质量思维链
- name: Selector
  thought: "用户询问天气但未指定城市和时间，我需要先收集这两个必要信息才能提供准确的天气预报。优先询问城市，因为这是最基本的查询条件。"
  result: Weather

# ❌ 低质量思维链  
- name: Selector
  thought: "选择天气"  # 过于简单，缺乏推理过程
  result: Weather
```

### 3. 数据覆盖策略
```yaml
# 覆盖用户表达的多样性
policies:
  - title: "问候-正式场合"
    actions:
      - name: UserUtter
        result: "您好，请问能帮我..."
        
  - title: "问候-日常对话"  
    actions:
      - name: UserUtter
        result: "嗨，我想要..."
        
  - title: "问候-简短表达"
    actions:
      - name: UserUtter
        result: "你好"
```

## 📊 数据质量评估

### 质量指标
- **完整性**：动作序列是否完整，覆盖完整对话流程
- **逻辑性**：思维链是否具有清晰的推理逻辑
- **一致性**：相似场景的处理方式是否一致
- **实用性**：是否贴近真实使用场景

### 测试验证
```yaml
# 在数据中添加测试用例
test_cases:
  - input: "我要退款"
    expected_trigger: "退款申请"
    expected_actions: ["UserUtter", "RefundProcess"]
    
  - input: "天气怎么样"
    expected_policy: "天气查询"
    expected_thought_quality: "high"  # 思维链质量要求
```

## 📚 完整配置示例

### 客服机器人数据配置

**policy/data.yml**:
```yaml
policies:
  - title: "智能客服问候"
    actions:
      - name: UserUtter
        result: "你好，我需要帮助"
      - name: Selector
        thought: "用户寻求帮助，我应该热情地回应并了解具体需求"
        result: BotUtter
      - name: BotUtter
        thought: "作为客服助手，我需要表现出专业和友好，同时引导用户说明问题"
        result: "您好！我是智能客服助手，很高兴为您服务。请告诉我您遇到了什么问题，我会尽力帮助您解决。"

  - title: "订单状态查询"
    actions:
      - name: UserUtter
        result: "我的订单什么时候能到？"
      - name: Selector
        thought: "用户询问订单配送时间，但没有提供订单号，我需要先获取订单信息"
        result: OrderQuery
      - name: OrderQuery
        result: "请提供您的订单号，我来帮您查询具体的配送状态"
      - name: UserUtter
        result: "202310151234"
      - name: OrderQuery
        result: "订单202310151234预计明天下午送达，当前状态：运输中"
      - name: Selector
        thought: "已获取订单信息，需要完整地告知用户配送情况和注意事项"
        result: BotUtter
      - name: BotUtter
        thought: "提供详细的配送信息，让用户了解时间安排，并提醒相关注意事项"
        result: "您的订单202310151234预计明天下午送达，目前正在运输途中。配送员会在送达前30分钟联系您，请保持手机畅通哦！"
```

**policy/rules.yml**:
```yaml
triggers:
  - title: "转人工客服"
    actions:
      - name: UserUtter
        result:
          - "转人工"
          - "人工客服"  
          - "真人服务"
          - "manual service"
      - name: TransferToHuman
        result: "正在为您转接人工客服，请稍候..."

  - title: "退款快速处理"
    actions:
      - name: UserUtter
        result:
          - "我要退款"
          - "申请退款"
          - "退款"
          - "refund"
      - name: RefundProcess
        result: "已为您启动退款流程"

  - title: "紧急情况"
    actions:
      - name: UserUtter
        result:
          - "紧急"
          - "urgent"
          - "很急"
          - "马上处理"
      - name: UrgentHandler
        result: "已标记为紧急事件，将优先处理"
```

通过精心设计的标注数据，COTA智能体能够学习到丰富的对话策略和处理模式，为用户提供更智能、更人性化的交互体验。建议从核心业务场景开始标注，逐步扩展覆盖面和复杂度。
