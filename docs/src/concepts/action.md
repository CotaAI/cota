# Action（动作）

动作(Action)是COTA框架中用户（User）或智能体（Agent）所产生的，能够影响对话状态（Dialogue State）的具体操作，它是智能体能感知的最小单元。用户和智能体通过执行不同的动作，来影响对话状态。本章会对不同的动作(Action)进行介绍。

## 🎯 基本介绍

用户执行UserUtter动作通过channel影响对话状态,智能体通过观察对话状态，选择合适的Action运行。Action在整个对话系统中处于核心位置，是连接用户意图和智能体响应的桥梁。

Action的定义和配置在`agent.yml`中，每个Action必须包含`description`和`prompt`这两个基本属性。

`description`是对Action的描述，表示action的作用，
agent会根据action的`description`结合对话状态来决定下一步执行的动作。因此不同Action的`description`的表述需要清晰、容易区分、
没有歧义。

`prompt`主要用于Action的执行，当机器人的某个动作要执行时，prompt会作为大语言模型（LLM）的输入，辅助Action的执行。

`description`和`prompt`是需要在action定义时显示的配置的，除此之外，每个Action还会有创建时间`timestamp`、发送人`sender_id`、
接收人`receiver_id`、执行结果`result`等属性用于对话过程的正常运行，以及action的序列化和反序列化。

不同类型的Action，如基本的Action和Form之间属性会有不同，Form还会有槽位`slots`、执行器`executer`属性，这些会在下面的介绍中详细说明。

## 🔧 动作类型

### UserUtter - 用户输入动作
UserUtter是用户的动作，当用户向智能体发送消息(Message)时，从智能体的视角，相当于用户执行了UserUtter这个Action，进而影响对话状态。用户发送的消息(Message)就作为UserUtter的执行结果。

UserUtter支持两种模式：
- **真实用户模式**：用户手动输入消息
- **代理用户模式**：通过LLM自动生成用户输入，用于数据生成和自动化测试

#### 配置示例

**基础配置（默认已包含）**：
```yaml
actions:
  UserUtter:
    description: "用户输入 - 此Action代表用户的输入消息，仅用于记录对话历史，Selector不应选择此Action"
```

**代理模式配置**：
```yaml
actions:
  UserUtter:
    description: "用户向智能体咨询"
    prompt: |
      你是一个需要帮助的用户，根据对话历史提出合理的问题或回应。
      
      **历史对话：**
      {{history_messages}}
      
      **输出格式：**
      ```json
      {
        "thought": "你的内心想法和推理过程",
        "text": "你要说的话", 
        "state": "continue/stop"
      }
      ```
```

**重要说明**：
- UserUtter在`constant.py`中已有默认配置，通常无需在`agent.yml`中重复定义
- 代理模式下必须配置UserUtter的prompt
- Selector不应选择UserUtter作为下一步动作

### BotUtter - 智能体回复动作
BotUtter是智能体的动作，代表智能体向用户发送消息(Message)，消息将通过通道（channel）发送给用户。通过`prompt`来控制BotUtter的执行过程，如引导回复的语气、扮演的角色、异常的处理等。

#### 配置示例
示例中的{{task_description}}和{{history_actions_with_thoughts}}都是DST提供的对话状态，这些对话状态在构建action的`prompt`时非常重要。DST(对话状态跟踪器)提供了丰富的状态，供智能体查询和使用。建议在prompt中指明输出格式，这会减少LLM出错的概率。

**基础BotUtter配置**：
```yaml
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

      请分析上述对话历史，参考学习资料中的思维模式，生成合适的JSON格式回复。
```

**支持知识库的BotUtter配置**：
```yaml
actions:
  BotUtter:
    description: "智能客服回复"
    prompt: |
      你是专业的客服助手，需要基于知识库和对话历史提供准确回复。

      **知识库信息：**
      {{knowledge}}
      
      **对话历史：**
      {{history_actions_with_thoughts}}
      
      **输出格式：**
      ```json
      {"thought": "<分析过程>", "text": "<回复内容>"}
      ```
```
**重要说明**：
- BotUtter支持思维链（Chain of Thought）输出，通过thought字段展示推理过程
- 支持知识库集成，通过{{knowledge}}变量获取RAG检索结果
- 输出必须为标准JSON格式，确保系统能正确解析

### Selector - 动作选择器
Selector是智能体的动作，用于判断智能体下一步应该执行哪个动作，Selector是让整个对话正常运转的关键。Selector根据智能体可选的Action列表，并依据历史的Action序列，从候选的Action列表中选择合适Action执行。

在一轮对话中，当用户执行UserUtter动作后，agent执行Selector选择候选的Action，执行Action，再通过Selector选择Action，继续执行，重复这个过程，直到达到对话结束条件。

#### 工作机制
- **思维链驱动**：通过DPL（对话策略学习）生成思考过程
- **上下文感知**：基于完整对话历史进行决策
- **规则避免**：自动排除不合适的Action（如UserUtter）

#### 配置示例
{{action_descriptions}}和{{history_actions_with_thoughts}}等为DST提供的对话状态，这些对话状态在构建action的`prompt`时非常重要。DST会自动处理Action过滤逻辑，比如{{action_descriptions}}中会排除Selector自身，防止陷入死循环。

```yaml
actions:
  Selector:
    description: "选择合适的Actions"
    prompt: |
      你是一个智能对话助手，需要根据当前对话状态选择下一个最合适的Action。

      **输出格式要求：**
      ```json
      {"thought": "<你的推理过程>", "action": "<工具名称>"}
      ```

      **可用的Action工具：**
      {{action_descriptions}}

      **决策参考模式：**
      {{policies}}

      **当前对话状态：**
      {{history_actions_with_thoughts}}

      请分析当前对话状态，参考决策模式，选择最合适的下一个Action并输出JSON格式结果。
```

### Form - 表单动作
Form(表单)是对话领域的一个基本概念，是一种结构化的数据收集工具，用于在对话系统中收集用户输入的信息并执行相应的业务逻辑。

在COTA中，Form是智能体的特殊动作类型，用于收集信息并执行特定的操作，Form在定制的业务场景中非常重要和实用。例如在查询天气的场景：收集城市→收集日期→调用天气接口→返回天气信息，这个完整的流程构成一个Form。

#### 核心组件
Form的定义由`description`、`prompt`、`slots`、`executer`等构成：

- **description**: 描述Form的作用和功能
- **prompt**: 统一处理槽位更新和结果返回的主要提示词  
- **slots**: 定义需要收集的信息槽位
- **executer**: 外部服务执行器，用于调用API或执行业务逻辑

#### 工作流程
1. **槽位收集**: 依次询问用户填充`slots`中定义的信息
2. **状态更新**: 通过主`prompt`智能解析用户输入并更新槽位状态
3. **完整性检查**: 当所有必需槽位填充完成后，进入执行阶段
4. **外部调用**: 通过`executer`调用外部API获取结果
5. **结果返回**: 将执行结果返回给用户

**优化说明**: 最新版本中，`updater`和`breaker`已被整合到主`prompt`中，简化了配置结构。

#### 配置示例
Form通过`slots`和`executer`属性被系统自动识别为Form类型的Action。最新版本简化了配置结构，不再需要单独的`updater`和`breaker`配置。

**完整的天气查询Form示例**：
```yaml
actions:
  Weather:
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

    slots:
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

    executer:
      url: http://rap2api.taobao.org/app/mock/319677/Weather
      method: GET
      output: ["<text>", "接口异常"]
      mock: false
```

**关键特性**：
- **统一提示词**: 主`prompt`处理所有槽位更新逻辑
- **JSON格式**: 槽位询问和结果返回都使用标准JSON格式
- **灵活配置**: 支持HTTP方法、输出格式和模拟模式配置
注意：Cota提供了丰富的mock api供开发者快速测试新建的对话，同时开发者也可以在CotaAI的cota-api仓库中提交自己mock的api。

### CustomAction - 自定义动作
在业务场景中，我们经常需要自定义Action，如计算器功能、查天气、转人工等。自定义Action非常简单，只需要在`agent.yml`中配置，这些自定义的Action会自动注册到智能体中。

#### 自定义基础类型的Action
如果你想自定义一个专门的回复Action，可以通过配置实现。不过鉴于BotUtter的灵活性，通常情况下直接使用BotUtter并通过不同的prompt来实现不同的回复风格更为合适。

##### 配置示例

```yaml
actions:
  CustomerService:
    description: "专业客服回复"
    prompt: |
      你是专业的客服代表，需要提供友好、准确的服务。

      **任务描述：**
      {{task_description}}

      **对话历史：**
      {{history_actions_with_thoughts}}

      **输出格式：**
      ```json
      {"thought": "<分析过程>", "text": "<客服回复>"}
      ```

      请以专业、友好的语气回复用户。
```

#### 自定义Form类型的Action
更常见的是自定义Form类型的Action，如查询天气、订餐或者定机票。Form类型的Action通过`slots`和`executer`属性被系统识别。

##### 转人工服务示例
```yaml
actions:
  RenGong:
    description: "转人工"
    executer:
      url: http://rap2api.taobao.org/app/mock/319677/Rengong
      method: GET
      output: ["成功", "失败"]
      mock: true
```

##### 复杂业务Form示例 - 订票服务
```yaml
actions:
  BookTicket:
    description: "预订机票"
    prompt: |
      当前正在执行{{current_form_name}}，需要收集订票信息。
      
      历史Action序列：{{history_actions_with_thoughts}}
      当前slots状态：{{current_form_slot_states}}
      槽位含义：{{current_form_slot_descriptions}}
      
      请根据用户输入更新槽位信息，输出JSON格式的slots状态。

    slots:
      departure:
        description: "出发城市"
        prompt: |
          请问您要从哪个城市出发？
          输出格式：{"text": "<询问出发城市的话>"}
          
      destination:
        description: "目的地城市"  
        prompt: |
          请问您要到哪个城市？
          输出格式：{"text": "<询问目的地的话>"}
          
      date:
        description: "出行日期"
        prompt: |
          请问您计划什么时候出行？
          输出格式：{"text": "<询问日期的话>"}

    executer:
      url: https://api.example.com/bookticket
      method: POST
      output: ["订票成功，订单号：{order_id}", "订票失败"]
      mock: false
```

## 📚 总结

Action是COTA框架的核心概念，通过不同类型的Action组合，可以构建功能强大的对话系统：

### 🎯 核心Action类型
- **UserUtter**: 用户输入，支持真实用户和代理模式
- **BotUtter**: 智能体回复，支持思维链和知识库集成  
- **Selector**: 动作选择器，决定对话流程
- **Form**: 表单动作，用于结构化数据收集和业务逻辑执行

### 🔧 配置要点
- 所有模板变量使用`{{variable}}`格式
- 输出格式统一为JSON，确保系统解析稳定
- Form配置已简化，主prompt统一处理槽位更新
- 支持思维链（Chain of Thought）提升对话可解释性

### 🚀 最佳实践
- 合理设计Action的`description`，确保Selector能准确选择
- 充分利用DST提供的丰富状态变量
- 在prompt中明确输出格式要求
- 对于复杂业务场景，优先使用Form类型Action
- 利用代理模式进行自动化测试和数据生成

通过灵活配置和组合这些Action，可以实现从简单问答到复杂业务流程的各种对话场景。
