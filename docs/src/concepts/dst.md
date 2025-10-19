# DST (对话状态跟踪器)

Dialogue State Tracker (DST) 是COTA框架中的关键组件，负责跟踪和更新对话状态。DST在多轮对话中扮演着"记忆"的角色，记录对话历史信息，帮助系统理解当前对话的上下文，并为Action提供丰富的状态变量。

## 🎯 核心功能

### 1. 状态维护
- **Action序列**: 维护完整的Action执行顺序和结构
- **对话历史**: 记录用户和智能体的完整交互历史
- **槽位状态**: 跟踪Form动作中的槽位填充状态
- **会话持久化**: 支持跨会话的状态保存和恢复

### 2. 状态提供
DST为Action的prompt提供丰富的状态变量，通过`{{}}`模板语法使用：
- **任务信息**: `{{task_description}}`等任务相关状态
- **对话历史**: `{{history_actions_with_thoughts}}`等历史信息
- **当前状态**: `{{current_form_name}}`等当前执行状态
- **知识信息**: `{{knowledge}}`等外部知识状态

### 3. 状态恢复
通过序列化机制，DST可以：
- 将对话状态保存到数据库（MySQL、Redis等）
- 在新会话中从数据库恢复历史状态
- 支持跨会话的连续对话体验

## 🔧 基本结构

DST的核心是Action列表，维护着整个对话的执行轨迹。通过DST中的Action序列和`agent.yml`配置，可以完整复现一个对话过程。

### 配置示例

在`agent.yml`中使用DST状态变量的示例：

```yaml
actions:
  BotUtter:
    description: "回复用户的提问"
    prompt: |
      根据任务描述和历史对话，生成回答。

      **任务描述：**
      {{task_description}}

      **对话历史：**
      {{history_actions_with_thoughts}}

      **学习参考资料：**
      {{policies}}

      **输出格式：**
      ```json
      {"thought": "<推理过程>", "text": "<回复内容>"}
      ```

  Selector:
    description: "选择合适的Actions"
    prompt: |
      根据当前对话状态选择下一个Action。

      **可用Actions：**
      {{action_descriptions}}

      **对话状态：**
      {{history_actions_with_thoughts}}

      **输出格式：**
      ```json
      {"thought": "<分析过程>", "action": "<动作名称>"}
      ```
```


## 📋 State变量列表

DST提供丰富的状态变量，覆盖任务、用户、动作、历史等多个维度。所有变量使用`{{variable_name}}`模板语法。

### 🎯 任务相关状态

#### task_description
- **描述**: Agent的任务描述，来自`agent.yml`中的`system.description`
- **使用场景**: 为Action提供角色和任务上下文
- **返回示例**: `"你是一名专业的宠物医生，需要认真负责地回答用户问题"`

### 👤 用户相关状态

#### history_messages
- **描述**: 原始消息历史，包含用户和机器人的对话内容
- **使用场景**: 主要用于UserUtter的代理模式
- **返回示例**: 
  ```
  用户: 你好
  机器人: 您好，请问有什么可以帮您的？
  用户: 我家猫咪不吃饭
  ```

#### latest_user_query
- **描述**: 用户最近一次的输入内容
- **使用场景**: 用于Form动作的跳出判断等
- **返回示例**: `"我家猫咪不吃饭，怎么办？"`

### 🔧 动作相关状态

#### action_descriptions
- **描述**: 所有可用Action的描述信息（通常排除UserUtter）
- **使用场景**: 主要用于Selector选择动作
- **返回示例**:
  ```
  BotUtter: 回复用户
  Weather: 查询天气
  RenGong: 转人工
  ```

#### current_action_name
- **描述**: 当前正在执行的Action名称
- **使用场景**: Form动作中使用
- **返回示例**: `"Weather"`

#### current_action_description  
- **描述**: 当前正在执行的Action描述
- **使用场景**: Form动作中提供上下文
- **返回示例**: `"查询天气"`

#### latest_action_name
- **描述**: 最近一次执行的Action名称
- **使用场景**: 状态跟踪和条件判断
- **返回示例**: `"Selector"`

#### latest_action_result
- **描述**: 最近一次Action的执行结果
- **使用场景**: 获取上一步的执行输出
- **返回示例**: `"Weather"`（如果上一步是Selector选择了Weather）

### 📚 历史序列相关状态

#### history_actions_with_thoughts
- **描述**: 带思维链的完整Action执行历史，是最重要的状态变量
- **使用场景**: BotUtter和Selector的主要输入，提供完整对话上下文
- **返回示例**:
  ```json
  [
    {
      "name": "UserUtter", 
      "result": "你好",
      "timestamp": 1760880555.173912
    },
    {
      "name": "Selector",
      "thought": "用户已打招呼，我应该回复用户以继续对话",
      "result": "BotUtter",
      "timestamp": 1760880555.174119
    },
    {
      "name": "BotUtter",
      "thought": "用户打招呼，我需要友好回应",
      "result": "你好，请问有什么可以帮您？",
      "timestamp": 1760880557.379215
    }
  ]
  ```

#### policies
- **描述**: 策略思维链参考数据，来自`policy/data.yml`
- **使用场景**: 为BotUtter和Selector提供学习参考模式
- **返回示例**: 包含历史标注数据的思维模式，用于指导当前决策

### 📋 Form相关状态

#### current_form_name
- **描述**: 当前执行的Form动作名称
- **使用场景**: Form动作的提示词中使用
- **返回示例**: `"Weather"`

#### current_form_description
- **描述**: 当前Form的描述信息
- **使用场景**: 为用户说明当前正在执行的业务
- **返回示例**: `"查询天气"`

#### current_form_slot_states
- **描述**: 当前Form的槽位状态（JSON格式）
- **使用场景**: Form的updater逻辑中使用
- **返回示例**:
  ```json
  {
    "city": "杭州",
    "time": null
  }
  ```

#### current_form_slot_descriptions
- **描述**: Form中各槽位的描述信息
- **使用场景**: 帮助LLM理解槽位含义
- **返回示例**:
  ```
  city: 城市，注意：接口只支持输入单个城市
  time: 时间
  ```

#### current_form_execute_result
- **描述**: Form执行器的返回结果
- **使用场景**: Form执行完成后，向用户展示结果
- **返回示例**: `"sunny"` (天气查询的结果)

### 🧠 知识相关状态

#### knowledge
- **描述**: 知识库检索结果（当配置了knowledge时可用）
- **使用场景**: BotUtter中集成外部知识
- **返回示例**: 
  ```
  根据您的问题，猫咪不吃饭可能的原因包括：
  1. 食物问题：食物变质或不新鲜
  2. 环境因素：换了新环境或有压力
  3. 健康问题：可能存在口腔疾病或消化问题
  建议先检查食物质量，观察猫咪其他行为...
  ```

## 🔄 状态生命周期

DST状态变量在对话过程中动态更新：

1. **会话开始**: 初始化基本状态，加载历史（如果有）
2. **用户输入**: 更新`latest_user_query`、`history_messages`等
3. **Action执行**: 更新`current_action_name`、action历史等
4. **Form处理**: 更新Form相关的所有状态变量
5. **会话结束**: 序列化状态到存储系统

## 📊 最佳实践

### 状态变量使用建议

1. **BotUtter动作**:
   - 必用: `{{history_actions_with_thoughts}}`、`{{task_description}}`
   - 推荐: `{{policies}}`（思维链学习）、`{{knowledge}}`（知识库）

2. **Selector动作**:
   - 必用: `{{action_descriptions}}`、`{{history_actions_with_thoughts}}`  
   - 推荐: `{{policies}}`（决策参考）

3. **Form动作**:
   - 必用: `{{current_form_slot_states}}`、`{{current_form_slot_descriptions}}`
   - 推荐: `{{history_actions_with_thoughts}}`、`{{current_form_name}}`

4. **UserUtter动作**（代理模式）:
   - 必用: `{{history_messages}}`
   - 推荐: `{{task_description}}`（角色扮演）

### 性能优化

- 合理使用状态变量，避免不必要的大量历史数据
- 对于长对话，考虑历史截断策略
- 利用缓存机制提升状态变量生成效率

通过合理使用这些状态变量，可以构建出上下文丰富、逻辑清晰的对话系统。


