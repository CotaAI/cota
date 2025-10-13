# Trigger配置详解

Trigger配置文件(`policy/rules.yml`)定义了智能体的触发规则，当用户输入匹配特定关键词或模式时，系统会自动执行预定义的动作序列，实现快速响应和精确处理。

## 📋 配置文件结构

```yaml
triggers:                    # 触发规则列表
  - title: "规则标题"        # 触发规则名称
    actions:                 # 触发的动作序列
      - name: UserUtter      # 用户输入匹配
        result:              # 匹配的内容列表
          - "关键词1"
          - "关键词2"
      - name: ActionName     # 触发的动作
        result: "预期结果"   # 预期的执行结果
```

## 🎯 Trigger的作用

### 1. 快速响应
- 无需复杂推理，直接匹配关键词
- 提供即时响应，提升用户体验
- 处理常见问题和标准流程

### 2. 精确控制
- 对特定输入执行特定动作
- 确保重要功能的可靠触发
- 避免误解和错误处理

### 3. 业务规则实现
- 实现业务逻辑的强制执行
- 处理合规要求和安全规则
- 支持工作流程的标准化

## 📝 详细配置说明

### 基本Trigger结构

```yaml
triggers:
  - title: "转人工"                 # 规则标题，用于标识和调试
    actions:                        # 动作序列
      - name: UserUtter             # 用户输入动作
        result:                     # 匹配的关键词列表
          - "转人工"
          - "人工客服"
          - "人工"
          - "人工服务"
          - "人工支持"
          - "人工咨询"
          - "人工解答"
          - "人工帮助"
      - name: RenGong               # 触发的动作
        result: "成功"              # 预期的执行结果
```

### 字段说明

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `title` | string | ✅ | 触发规则标题，用于识别和调试 |
| `actions` | array | ✅ | 触发的动作序列 |
| `name` | string | ✅ | 动作名称，必须在agent.yml中定义 |
| `result` | string/array | ✅ | 匹配内容或执行结果 |

## 🔧 匹配机制

### 1. 精确匹配
用户输入必须完全匹配列表中的某个关键词：

```yaml
triggers:
  - title: "精确匹配示例"
    actions:
      - name: UserUtter
        result:
          - "退款"      # 只匹配"退款"
          - "退钱"      # 只匹配"退钱"
          - "refund"    # 只匹配"refund"
      - name: RefundAction
        result: "启动退款流程"
```

### 2. 包含匹配
如果关键词出现在用户输入中，即可触发：

```yaml
triggers:
  - title: "包含匹配示例"
    actions:
      - name: UserUtter
        result:
          - "投诉"          # "我要投诉"、"投诉处理"都能匹配
          - "不满意"        # "对服务不满意"能匹配
          - "问题"          # "有什么问题"能匹配
      - name: ComplaintAction
        result: "转至投诉处理"
```

## 🎨 常见Trigger模式

### 1. 服务转接类

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
          - "人工坐席"
          - "manual service"
          - "human agent"
      - name: TransferToHuman
        result: "正在为您转接人工客服..."

  - title: "转技术支持"
    actions:
      - name: UserUtter
        result:
          - "技术支持"
          - "技术问题"
          - "bug反馈"
          - "系统故障"
          - "technical support"
      - name: TransferToTech
        result: "正在为您转接技术支持..."
```

### 2. 业务操作类

```yaml
triggers:
  - title: "退款申请"
    actions:
      - name: UserUtter
        result:
          - "退款"
          - "退钱"
          - "申请退款"
          - "退款申请"
          - "我要退款"
          - "refund"
      - name: RefundProcess
        result: "已启动退款流程"

  - title: "订单查询"
    actions:
      - name: UserUtter
        result:
          - "查订单"
          - "订单状态"
          - "我的订单"
          - "订单查询"
          - "order status"
          - "check order"
      - name: OrderQuery
        result: "请提供您的订单号"
```

### 3. 紧急处理类

```yaml
triggers:
  - title: "紧急情况"
    actions:
      - name: UserUtter
        result:
          - "紧急"
          - "urgent"
          - "emergency"
          - "很急"
          - "马上"
          - "立即"
      - name: UrgentHandler
        result: "已标记为紧急事件，优先处理"

  - title: "投诉升级"
    actions:
      - name: UserUtter
        result:
          - "投诉"
          - "complaint"
          - "不满意"
          - "差评"
          - "服务态度"
          - "要投诉"
      - name: ComplaintEscalation
        result: "已升级至投诉处理部门"
```

## 🔄 复杂Trigger配置

### 1. 多步骤触发

```yaml
triggers:
  - title: "多步骤退款流程"
    actions:
      - name: UserUtter
        result:
          - "我要退款"
          - "申请退款"
      - name: RefundCheck        # 第一步：检查退款条件
        result: "符合退款条件"
      - name: RefundForm         # 第二步：填写退款表单
        result: "请填写退款信息"
      - name: RefundSubmit       # 第三步：提交申请
        result: "退款申请已提交"
```

### 2. 条件分支触发

```yaml
triggers:
  - title: "VIP客户专属服务"
    actions:
      - name: UserUtter
        result:
          - "VIP服务"
          - "我是VIP"
          - "会员专线"
      - name: VipCheck           # 检查VIP状态
        result: "已验证VIP身份"
      - name: VipService         # VIP专属服务
        result: "为您提供VIP专属服务"

  - title: "普通客户服务"
    actions:
      - name: UserUtter
        result:
          - "客服"
          - "服务"
          - "帮助"
      - name: RegularService     # 普通服务
        result: "为您提供标准服务"
```

### 3. 多语言支持

```yaml
triggers:
  - title: "多语言问候"
    actions:
      - name: UserUtter
        result:
          # 中文问候
          - "你好"
          - "您好"
          - "hi"
          - "hello"
          # 英文问候
          - "good morning"
          - "good afternoon"
          - "good evening"
          # 其他语言
          - "bonjour"      # 法语
          - "guten tag"    # 德语
          - "こんにちは"    # 日语
      - name: MultiLangGreeting
        result: "欢迎使用多语言服务！"
```

## ⚙️ 高级配置技巧

### 1. 优先级控制

通过配置顺序控制触发优先级：

```yaml
triggers:
  # 高优先级：紧急情况
  - title: "紧急退款"
    actions:
      - name: UserUtter
        result: ["紧急退款", "急需退款"]
      - name: UrgentRefund
        result: "紧急退款处理"
  
  # 中优先级：普通退款
  - title: "普通退款"
    actions:
      - name: UserUtter
        result: ["退款", "退钱"]
      - name: RegularRefund
        result: "普通退款处理"
  
  # 低优先级：一般咨询
  - title: "退款咨询"
    actions:
      - name: UserUtter
        result: ["退款政策", "如何退款"]
      - name: RefundInfo
        result: "退款政策说明"
```

### 2. 正则表达式支持（高级）

```yaml
triggers:
  - title: "订单号匹配"
    actions:
      - name: UserUtter
        result:
          - "/^订单号[：:]?\\s*\\d{10,}$/"    # 正则匹配订单号格式
          - "/^order\\s*#?\\s*\\d{10,}$/i"   # 英文订单号格式
      - name: OrderNumberRecognized
        result: "已识别订单号"

  - title: "手机号匹配"
    actions:
      - name: UserUtter
        result:
          - "/^1[3-9]\\d{9}$/"               # 匹配中国手机号
          - "/^\\+?1[0-9]{10}$/"             # 匹配美国手机号
      - name: PhoneNumberRecognized
        result: "已识别手机号"
```

### 3. 上下文相关触发

```yaml
triggers:
  - title: "确认操作"
    conditions:                              # 添加上下文条件
      last_action: "ConfirmationRequest"     # 上一个动作是确认请求
    actions:
      - name: UserUtter
        result:
          - "是"
          - "确认"
          - "yes"
          - "ok"
          - "好的"
      - name: ConfirmAction
        result: "操作已确认"

  - title: "取消操作"
    conditions:
      last_action: "ConfirmationRequest"
    actions:
      - name: UserUtter
        result:
          - "不"
          - "取消"
          - "no"
          - "算了"
      - name: CancelAction
        result: "操作已取消"
```

## 📊 Trigger性能优化

### 1. 关键词优化

```yaml
# ✅ 好的做法：关键词清晰、不重复
triggers:
  - title: "退款类"
    actions:
      - name: UserUtter
        result:
          - "退款"          # 核心词
          - "退钱"          # 近义词
          - "refund"        # 英文
      - name: RefundAction
        result: "退款处理"

# ❌ 避免：关键词过多、有歧义
triggers:
  - title: "退款类-过度配置"
    actions:
      - name: UserUtter
        result:
          - "退款"
          - "退钱"
          - "退"           # 太简单，容易误匹配
          - "钱"           # 太宽泛
          - "退款退款"      # 重复
```

### 2. 匹配策略优化

```yaml
# 分层匹配：先精确匹配，再模糊匹配
triggers:
  # 第一层：精确匹配
  - title: "精确-转人工"
    actions:
      - name: UserUtter
        result: ["转人工", "人工客服"]
      - name: DirectTransfer
        result: "直接转人工"
  
  # 第二层：模糊匹配
  - title: "模糊-需要帮助"
    actions:
      - name: UserUtter
        result: ["帮助", "help", "求助"]
      - name: HelpRequest
        result: "提供帮助选项"
```

## 🔍 调试和监控

### 1. 触发日志

```yaml
# 在agent.yml中配置日志级别
logging:
  trigger:
    level: DEBUG              # 启用详细的触发日志
    log_matches: true         # 记录匹配过程
    log_non_matches: false    # 不记录未匹配的情况
```

### 2. 统计信息

```yaml
# 添加统计元数据
metadata:
  trigger_stats:
    total_rules: 10           # 总规则数
    active_rules: 8           # 活跃规则数
    match_rate: 0.75          # 匹配成功率
    avg_response_time: 50     # 平均响应时间（毫秒）
```

## 🚨 常见配置错误

### 1. 关键词冲突

```yaml
# ❌ 错误：关键词在多个规则中重复
triggers:
  - title: "退款处理"
    actions:
      - name: UserUtter
        result: ["退款"]
      - name: RefundAction
        result: "退款"
        
  - title: "退款咨询"
    actions:
      - name: UserUtter
        result: ["退款"]      # 与上面冲突
      - name: RefundInfo
        result: "咨询"

# ✅ 正确：明确区分不同场景
triggers:
  - title: "退款申请"
    actions:
      - name: UserUtter
        result: ["我要退款", "申请退款"]
      - name: RefundAction
        result: "退款"
        
  - title: "退款政策"
    actions:
      - name: UserUtter
        result: ["退款政策", "如何退款"]
      - name: RefundInfo
        result: "咨询"
```

### 2. 动作配置错误

```yaml
# ❌ 错误：动作名称不存在
triggers:
  - title: "转人工"
    actions:
      - name: UserUtter
        result: ["转人工"]
      - name: UnknownAction    # agent.yml中未定义此动作
        result: "success"

# ✅ 正确：使用已定义的动作
triggers:
  - title: "转人工"
    actions:
      - name: UserUtter
        result: ["转人工"]
      - name: RenGong          # 在agent.yml中已定义
        result: "成功"
```

### 3. 结果格式错误

```yaml
# ❌ 错误：结果格式不统一
triggers:
  - title: "格式错误"
    actions:
      - name: UserUtter
        result: "单个字符串"    # 字符串格式
      - name: UserUtter
        result: ["数组格式"]   # 数组格式，不一致

# ✅ 正确：统一使用数组格式
triggers:
  - title: "格式正确"
    actions:
      - name: UserUtter
        result: 
          - "格式1"
          - "格式2"
```

## 📚 Trigger模板

### 客服场景模板

```yaml
triggers:
  # 转人工
  - title: "转人工客服"
    actions:
      - name: UserUtter
        result: ["转人工", "人工客服", "真人服务"]
      - name: TransferHuman
        result: "转接成功"
  
  # 投诉处理
  - title: "投诉升级"
    actions:
      - name: UserUtter
        result: ["投诉", "不满意", "差评"]
      - name: ComplaintHandler
        result: "投诉处理"
  
  # 退款申请
  - title: "退款申请"
    actions:
      - name: UserUtter
        result: ["退款", "退钱", "申请退款"]
      - name: RefundProcess
        result: "退款处理"
```

### 电商场景模板

```yaml
triggers:
  # 订单查询
  - title: "订单查询"
    actions:
      - name: UserUtter
        result: ["查订单", "订单状态", "我的订单"]
      - name: OrderQuery
        result: "订单查询"
  
  # 物流跟踪
  - title: "物流查询"
    actions:
      - name: UserUtter
        result: ["物流", "快递", "配送进度"]
      - name: LogisticsTrack
        result: "物流查询"
  
  # 商品咨询
  - title: "商品咨询"
    actions:
      - name: UserUtter
        result: ["商品详情", "产品介绍", "商品信息"]
      - name: ProductInfo
        result: "商品信息"
```

通过合理配置Trigger规则，你可以让COTA智能体快速、准确地响应用户的特定需求，提供高效的自动化服务。建议从最常见的业务场景开始配置，逐步完善规则覆盖面。
