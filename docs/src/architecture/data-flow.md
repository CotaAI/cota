# 数据流设计

COTA框架采用事件驱动的数据流设计，数据在各个组件间按照明确的路径和协议进行传递。本文档详细分析数据在系统中的流转过程和设计原理。

## 🌊 整体数据流概览

```mermaid
graph TD
    subgraph "输入层"
        User[用户输入]
        ExternalAPI[外部API]
        FileSystem[文件系统]
    end
    
    subgraph "接入层"
        Channels[通道系统]
        Server[Web服务器]
    end
    
    subgraph "处理层"
        Message[消息对象]
        Processor[处理器]
        DST[状态跟踪]
        DPL[策略学习]
    end
    
    subgraph "执行层"
        Actions[动作系统]
        Executors[执行器]
        LLM[语言模型]
    end
    
    subgraph "存储层"
        Memory[内存存储]
        Database[数据库]
        Cache[缓存系统]
    end
    
    User --> Channels
    ExternalAPI --> Server
    
    Channels --> Message
    Server --> Message
    
    Message --> Processor
    Processor --> DST
    Processor --> DPL
    
    DPL --> Actions
    Actions --> Executors
    Actions --> LLM
    
    DST --> Memory
    DST --> Database
    Processor --> Cache
    
    LLM --> Processor
    Executors --> Processor
```

## 📨 消息处理流程

### 基础消息流

```mermaid
sequenceDiagram
    participant U as 用户
    participant C as 通道
    participant A as 智能体
    participant P as 处理器
    participant D as DST
    participant DPL as DPL
    participant Act as 动作
    participant L as LLM
    participant S as 存储
    
    U->>C: 发送消息
    Note over C: 消息格式转换
    C->>A: 转发Message对象
    A->>P: handle_message()
    
    Note over P: 构建UserUtter动作
    P->>D: get_tracker(session_id)
    S-->>D: 返回DST实例
    D-->>P: DST状态
    
    P->>D: update(UserUtter)
    Note over D: 更新对话状态
    
    P->>P: _handle_bot_actions()
    
    loop 动作执行循环
        P->>DPL: generate_actions(DST)
        DPL->>L: generate_chat() [if needed]
        L-->>DPL: LLM响应
        DPL-->>P: 动作列表
        
        P->>Act: run(agent, dst)
        Act->>L: 调用LLM [if needed]
        L-->>Act: 生成结果
        Act-->>P: 动作结果
        
        P->>D: update(动作)
        P->>C: send_response() [if BotUtter]
        
        alt 如果是BotUtter
            break 结束循环
        end
    end
    
    P->>S: save_tracker(DST)
    C-->>U: 返回响应
```

### 消息对象结构

```python
# 消息数据结构
class Message:
    def __init__(self):
        self.text: str          # 消息文本
        self.sender: str        # 发送者角色 (user/bot)
        self.sender_id: str     # 发送者ID
        self.receiver: str      # 接收者角色
        self.receiver_id: str   # 接收者ID
        self.session_id: str    # 会话ID
        self.metadata: Dict     # 元数据
        self.timestamp: datetime # 时间戳
```

### 数据转换过程

```mermaid
graph LR
    subgraph "输入转换"
        RawInput[原始输入] --> MessageFormat[消息格式化]
        MessageFormat --> Validation[数据验证]
        Validation --> MessageObj[Message对象]
    end
    
    subgraph "状态转换"
        MessageObj --> UserUtter[UserUtter动作]
        UserUtter --> StateUpdate[状态更新]
        StateUpdate --> DSTObj[DST对象]
    end
    
    subgraph "处理转换"
        DSTObj --> ActionGen[动作生成]
        ActionGen --> ActionExec[动作执行]
        ActionExec --> Result[执行结果]
    end
    
    subgraph "输出转换"
        Result --> ResponseFormat[响应格式化]
        ResponseFormat --> ChannelOutput[通道输出]
        ChannelOutput --> UserResponse[用户响应]
    end
```

## 🧠 智能决策数据流

### DPL策略决策流程

```mermaid
graph TD
    DST[当前对话状态] --> DPLInput[DPL输入]
    
    subgraph "策略类型"
        TriggerDPL[触发式策略]
        MatchDPL[匹配式策略]
        RAGDPL[RAG策略]
    end
    
    DPLInput --> TriggerDPL
    DPLInput --> MatchDPL
    DPLInput --> RAGDPL
    
    subgraph "数据处理"
        TriggerDPL --> RuleMatch[规则匹配]
        MatchDPL --> PatternMatch[模式匹配]
        RAGDPL --> LLMCall[LLM调用]
    end
    
    RuleMatch --> ActionPredict[动作预测]
    PatternMatch --> ThoughtGen[思维链生成]
    LLMCall --> ContentGen[内容生成]
    
    ActionPredict --> DPLOutput[DPL输出]
    ThoughtGen --> DPLOutput
    ContentGen --> DPLOutput
    
    DPLOutput --> ActionSelection[动作选择]
```

### 思维链生成流程

```mermaid
sequenceDiagram
    participant DST as 对话状态
    participant DPL as DPL策略
    participant PolicyData as 策略数据
    participant LLM as 语言模型
    participant ThoughtChain as 思维链
    
    DST->>DPL: 请求思维链生成
    DPL->>PolicyData: 查询历史模式
    PolicyData-->>DPL: 返回匹配模式
    
    alt 匹配式策略
        DPL->>DPL: 基于模式生成思维链
    else RAG策略
        DPL->>LLM: 发送生成请求
        LLM-->>DPL: 返回生成内容
    end
    
    DPL->>ThoughtChain: 构建思维链
    ThoughtChain-->>DST: 返回思维链内容
```

## ⚡ 动作执行数据流

### 动作生命周期

```mermaid
stateDiagram-v2
    [*] --> Created: 创建动作
    Created --> Initialized: 初始化
    Initialized --> Running: 开始执行
    
    Running --> Formatting: 格式化提示词
    Formatting --> LLMCall: 调用LLM
    LLMCall --> Processing: 处理响应
    Processing --> FormAction: 表单动作?
    
    FormAction --> SlotFilling: 槽位填充
    FormAction --> ExecutorCall: 执行器调用
    FormAction --> Completed: 完成
    
    SlotFilling --> AskUser: 询问用户
    AskUser --> Completed
    
    ExecutorCall --> ExternalAPI: 外部API
    ExternalAPI --> Completed
    
    Processing --> Completed: 普通动作
    Completed --> [*]
```

### 表单动作数据流

```mermaid
graph TD
    FormStart[表单开始] --> CheckSlots[检查槽位]
    
    CheckSlots --> MissingSlots{有缺失槽位?}
    MissingSlots -->|是| AskSlot[询问槽位]
    MissingSlots -->|否| ExecuteCall[执行外部调用]
    
    AskSlot --> UserResponse[用户响应]
    UserResponse --> UpdateSlots[更新槽位]
    UpdateSlots --> CheckSlots
    
    ExecuteCall --> Executor[执行器]
    Executor --> HTTPCall[HTTP调用]
    Executor --> PythonScript[Python脚本]
    Executor --> ShellScript[Shell脚本]
    
    HTTPCall --> APIResponse[API响应]
    PythonScript --> ScriptResult[脚本结果]
    ShellScript --> CommandOutput[命令输出]
    
    APIResponse --> FormatResult[格式化结果]
    ScriptResult --> FormatResult
    CommandOutput --> FormatResult
    
    FormatResult --> FormComplete[表单完成]
```

### 执行器数据流

```mermaid
sequenceDiagram
    participant Action as 动作
    participant Executor as 执行器
    participant HttpClient as HTTP客户端
    participant ExternalAPI as 外部API
    participant Result as 结果处理
    
    Action->>Executor: execute(data)
    Executor->>HttpClient: 创建HTTP请求
    HttpClient->>ExternalAPI: 发送请求
    
    ExternalAPI-->>HttpClient: 返回响应
    HttpClient-->>Executor: HTTP响应
    
    Executor->>Result: 处理响应数据
    Result->>Result: 格式化结果
    Result-->>Action: 返回结果
```

## 🗄️ 状态管理数据流

### DST状态更新

```mermaid
graph TD
    Action[动作执行] --> Apply[apply_to(DST)]
    Apply --> UpdateState[更新状态字段]
    
    UpdateState --> UpdateActions[更新动作队列]
    UpdateState --> UpdateSlots[更新槽位信息]
    UpdateState --> UpdateForm[更新当前表单]
    UpdateState --> UpdateLatest[更新最新信息]
    
    subgraph "状态字段"
        Actions[actions队列]
        FormlessActions[formless_actions队列]
        Slots[slots字典]
        CurrentForm[current_form]
        LatestAction[latest_action]
        LatestQuery[latest_query]
        LatestResponse[latest_response]
    end
    
    UpdateActions --> Actions
    UpdateActions --> FormlessActions
    UpdateSlots --> Slots
    UpdateForm --> CurrentForm
    UpdateLatest --> LatestAction
    UpdateLatest --> LatestQuery
    UpdateLatest --> LatestResponse
```

### 状态持久化

```mermaid
sequenceDiagram
    participant Processor as 处理器
    participant DST as 对话状态
    participant Store as 存储系统
    participant Database as 数据库
    
    Processor->>DST: 获取状态数据
    DST->>DST: as_dict()
    DST-->>Processor: 状态字典
    
    Processor->>Store: save(tracker)
    Store->>Store: 序列化数据
    Store->>Database: 执行SQL插入/更新
    
    Database-->>Store: 操作结果
    Store-->>Processor: 保存完成
    
    Note over Database: 数据结构:<br/>session_id, actions, slots, timestamp
```

## 🔄 多智能体数据流

### Task任务编排

```mermaid
graph TD
    TaskConfig[任务配置] --> TaskLoader[任务加载器]
    TaskLoader --> PlanParser[计划解析器]
    
    PlanParser --> StaticPlan[静态计划]
    PlanParser --> DynamicPlan[动态计划]
    
    StaticPlan --> DAGBuilder[DAG构建器]
    DynamicPlan --> LLMPlanner[LLM规划器]
    
    DAGBuilder --> TaskScheduler[任务调度器]
    LLMPlanner --> TaskScheduler
    
    TaskScheduler --> Agent1[智能体1]
    TaskScheduler --> Agent2[智能体2]
    TaskScheduler --> AgentN[智能体N]
    
    Agent1 --> Result1[结果1]
    Agent2 --> Result2[结果2]
    AgentN --> ResultN[结果N]
    
    Result1 --> TaskCollector[结果收集器]
    Result2 --> TaskCollector
    ResultN --> TaskCollector
    
    TaskCollector --> TaskResult[任务结果]
```

### 智能体间通信

```mermaid
sequenceDiagram
    participant TaskManager as 任务管理器
    participant Agent1 as 智能体1
    participant Agent2 as 智能体2
    participant SharedStore as 共享存储
    
    TaskManager->>Agent1: 启动任务1
    Agent1->>Agent1: 处理消息
    Agent1->>SharedStore: 保存中间结果
    
    TaskManager->>Agent2: 启动任务2
    Agent2->>SharedStore: 获取Agent1结果
    SharedStore-->>Agent2: 返回数据
    Agent2->>Agent2: 处理数据
    Agent2->>SharedStore: 保存最终结果
    
    TaskManager->>SharedStore: 收集所有结果
    SharedStore-->>TaskManager: 返回完整结果
```

## 📊 数据格式和协议

### 标准数据格式

**1. 消息格式**
```json
{
  "type": "text",
  "sender": "user",
  "sender_id": "user_123",
  "receiver": "bot",
  "receiver_id": "bot_456",
  "session_id": "session_789",
  "text": "用户消息内容",
  "metadata": {
    "timestamp": "2024-01-01T00:00:00Z",
    "channel": "websocket"
  }
}
```

**2. 动作格式**
```json
{
  "name": "BotUtter",
  "description": "机器人回复",
  "timestamp": "2024-01-01T00:00:00Z",
  "result": [
    {
      "text": "机器人回复内容",
      "sender": "bot",
      "sender_id": "bot_456",
      "receiver": "user",
      "receiver_id": "user_123"
    }
  ]
}
```

**3. 状态格式**
```json
{
  "session_id": "session_789",
  "slots": {
    "city": "北京",
    "date": "今天"
  },
  "actions": [
    {
      "name": "UserUtter",
      "result": [{"text": "查询北京今天天气"}]
    },
    {
      "name": "BotUtter", 
      "result": [{"text": "北京今天晴天，25°C"}]
    }
  ]
}
```

### 通信协议

**1. WebSocket协议**
```javascript
// 客户端发送
{
  "event": "user_message",
  "data": {
    "text": "用户消息",
    "session_id": "session_123"
  }
}

// 服务端响应
{
  "event": "bot_response",
  "data": {
    "text": "机器人回复",
    "session_id": "session_123"
  }
}
```

**2. REST API协议**
```http
POST /api/chat
Content-Type: application/json

{
  "message": "用户消息",
  "session_id": "session_123",
  "user_id": "user_456"
}

HTTP/1.1 200 OK
Content-Type: application/json

{
  "response": "机器人回复",
  "session_id": "session_123",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

## 🚀 性能优化

### 数据流优化策略

```mermaid
graph TD
    subgraph "输入优化"
        BatchInput[批量输入处理]
        Validation[数据验证缓存]
        Compression[数据压缩]
    end
    
    subgraph "处理优化"
        AsyncProcess[异步处理]
        Pipeline[流水线处理]
        Cache[结果缓存]
    end
    
    subgraph "存储优化"
        ConnectionPool[连接池]
        BatchWrite[批量写入]
        IndexOptimize[索引优化]
    end
    
    subgraph "输出优化"
        ResponseCache[响应缓存]
        Streaming[流式响应]
        CDN[内容分发]
    end
    
    BatchInput --> AsyncProcess
    Validation --> Pipeline
    Compression --> Cache
    
    AsyncProcess --> ConnectionPool
    Pipeline --> BatchWrite
    Cache --> IndexOptimize
    
    ConnectionPool --> ResponseCache
    BatchWrite --> Streaming
    IndexOptimize --> CDN
```

### 缓存策略

**1. 多层缓存**
- **L1 缓存**: 内存缓存 (最近访问的DST状态)
- **L2 缓存**: Redis缓存 (会话数据和LLM响应)
- **L3 缓存**: 数据库缓存 (持久化历史数据)

**2. 缓存失效策略**
- **TTL**: 时间过期自动失效
- **LRU**: 最近最少使用淘汰
- **版本号**: 数据更新时主动失效

### 并发控制

```mermaid
graph TD
    Request[并发请求] --> Semaphore[信号量控制]
    Semaphore --> Queue[请求队列]
    Queue --> WorkerPool[工作线程池]
    
    WorkerPool --> Worker1[工作线程1]
    WorkerPool --> Worker2[工作线程2]
    WorkerPool --> WorkerN[工作线程N]
    
    Worker1 --> DST1[DST实例1]
    Worker2 --> DST2[DST实例2]
    WorkerN --> DSTN[DST实例N]
    
    DST1 --> Response1[响应1]
    DST2 --> Response2[响应2]
    DSTN --> ResponseN[响应N]
```

通过这种精心设计的数据流架构，COTA能够高效、可靠地处理复杂的对话场景，同时保证系统的可扩展性和可维护性。
