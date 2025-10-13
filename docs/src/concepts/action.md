动作(Action)是指用户（User）或智能体（Agent）所产生的，能够影响对话状态（Dialogue State）的具体操作，它是智能体能感知的最小单元。
用户和智能体通过执行不同的动作，来影响对话状态。本章会对不同的动作(Action)进行介绍。

## 基本介绍
用户执行动作Query通过channel影响对话状态,智能体通过观察对话状态，选择合适的Action运行。这段话描述了Action在整个对话系统中的位置。

Action结合以及定义配置在task.yml中，每个Action（Query除外）必须包含`description`和`prompt`这两个基本属性。

`description`是对Action的描述，表示action的作用，
agent会根据action的`description`结合对话状态来决定下一步执行的动作。因此不同Action的`description`的表述需要清晰、容易区分、
没有歧义。

`prompt`主要用于Action的执行，当机器人的某个动作要执行时，prompt会作为大语言模型（LLM）的输入，辅助Action的执行。

`description`和`prompt`是需要在action定义时显示的配置的，除此之外，每个Action还会有创建时间`timestamp`、发送人`sender_id`、
接收人`receiver_id`、执行结果`result`等属性用于对话过程的正常运行，以及action的序列化和反序列化。

不同类型的Action，如基本的Action
和Form之间属性会有不同，Form还会有槽位`slots`、更新器`updater`、跳出器`breaker`、执行器`exectuer`属性，这些会在下面的介绍中详细说明。

## 动作类型
### Query
Query是用户的动作，当用户向智能体发送消息(Message)时，从智能体的视角，相当于用户执行了Query这个Action，进而影响对话状态。
用户发送的消息(Message)就作为Query的执行结果。

#### 配置示例

```yaml
actions:
  Query:
    description: "User的动作，用于用户向智能体发送消息"
```

注意：在当前版本中，Query只作为用户的动作，因此不能被agent选择，因此`description`和`prompt`无需配置，但建议配置`description`增加配置
的易读性。

### Response
Response是智能体的动作，代表智能体向用户发送消息(Message)，消息将通过通道（channel）发送给用户。通过`prompt`来控制Response的执行过程，
如引导回复的语气、扮演的角色、异常的处理等。

#### 配置示例
示例中的{task_description} 和 {history_messages} 都是DST提供的对话状态，这些对话状态在构建action的`prompt`时非常重要，DST(对话状态跟踪器)提供
了丰富的状态，供智能体查询和使用，这部分内容在DST部分有详细介绍。同时，建议在prompt中指明输出格式，这会减少LLM出错的概率。

```yaml
actions:
  Response:
    description: "回复用户的提问"
    prompt: |
      根据任务描述和历史对话，生成回答。

      任务描述:
      {task_description}

      历史对话:
      {history_messages}

      输出格式为: <回答用户的话>

```
注意：推荐在配置时，通过如上的方式换行，这会增加配置文件的易读性。

### Selector
Selector是智能体的动作，用于判断智能体下一步应该执行哪个动作，Selector是让整个对话正常运转的关键。
Selector根据智能体可选的Action列表，并依据历史的Action序列，从候选的Action列表中选择合适Action
执行。

在一轮对话中，当用户执行Query动作后，agent执行Selector选择候选的Action，执行Action，再通过Selector
选择Action，继续执行，重复这个过程，直到执行的Action为Response，代表着本轮对话的结束。

#### 配置示例
{bot_action_names_for_selector}等为DST提供的对话状态，这些对话状态在构建action的`prompt`时非常重要，DST(对话状态跟踪器)提供
了丰富的状态，供智能体查询和使用，有些状态是某些Action准备的，比如{bot_action_names_for_selector}中，会返回处Selector之外的agent
的actions, 以防止陷入死循环这种意外情况，当然也可以使用其它的状态，这部分内容在DST部分有详细介绍。

```yaml
actions:
  Selector:
    description: "选择合适的Actions"
    prompt: |
      根据历史Action序列，结合Action的描述，从Action列表中，选择最合适的Action。

      Action列表:
      {bot_action_names_for_selector}

      Action描述为:
      {bot_action_descriptions_for_selector}

      历史Action序列为:
      {history_actions_for_selector}

      输出格式为: <Action>

```

### Form
Form(表单)是对话领域的一个基本概念，通常表述其为一种结构化的数据收集工具，用于在对话系统中收集用户输入的信息。

在Cota中，Form也是智能体的动作，它是一种特殊类型的智能体Action，用于收集信息并执行特定的动作，Form在定制的业务场景中非常重要和实用。
例如在查询天气的场景，城市->收集日期->调用查询天气接口->将天气情况返回给用户，这些动作和接口调用的集合构成一个Form。

Form的定义比较复杂，由`description`, `prompt`, `slots`, `updater`, `breaker`, `executer` 等构成。

`slots`代表Form需要收集哪些信息，agent会询问用户来获得slot的值，对于每个slot，agent会使用Response动作来发起询问，因此对于每个slot
同样需要配置`description`和`prompt`。

`updater`用于维护Form的slots的状态，它会根据当前Form的slots，结合历史对话，更新slots状态。`updater`也是通过LLM来运行的，因此对于
`updater`也需要配置`description`和`prompt`。

`breaker`用于判断是否从当前Form中退出，这对于用户重新咨询一个新问题时非常重要。`breaker`也是通过LLM来运行的，因此对于
`breaker`也需要配置`description`和`prompt`。

当`slots`收集完整，并且合法后，`executer`会执行，并将结果写入Form的result中。当前版本中`exectuer`被配置为http请求，以方便不同的业务定义
自己的Form和执行逻辑。

#### 配置示例
Form继承于Action的，同时Form拥有`slots`, `updater`, `breaker`, `executer`属性。在使用Form时，你需要配置一个自定义的Action
继承Form，自定义Action的时候，如果拥有executer或者slots属性的Action，就会被系统识别为Form类型的Action。

虽然Form的配置项较多，但对于`updater`, `breaker`的配置，基本是不随业务变化的，可以省略，使用系统配置好的模板。

```yaml
actions:
  Weather:
    description: "查询天气"
    prompt: |
      当前正在执行{current_form_name}, 其描述为{current_form_description}。将计算结果返给用户,注意: 严格按照计算结果返还用户，不要自己计算。
      输入:
      {current_form_slots_state} 
      计算结果为
      {current_form_execute_result}

    updater:
      description: "更新状态"
      prompt: |
        当前正在执行{current_form_name}， 其描述为{current_form_description}。根据对话内容及Action序列，结合当前slot的状态，填充或重置slot的值。
        
        历史Action序列为:
        {history_actions_for_update}

        Action的描述为:
        {action_descriptions}

        当前slots为:
        {current_form_slots_state}

        slots的含义为:
        {current_form_slots_description}
        
        填充或重置slot的值, 保持slots格式输出json字符串。

    breaker:
      description: "判断是否跳出"
      prompt: |
        当前正在执行{current_form_name}， 其描述为{current_form_description}。根据对话内容，结合用户最近的对话，判读用户意图，决定是否跳出当前Action.

        对话内容:
        {history_messages}

        用户最后对话：
        {latest_user_query}

        如果当前用户意图和{current_form_name}无关，则跳出当前Action, 输出标识符true。
        如果当前用户意图和{current_form_name}有关，则维持当前Action, 输出标识符false。

        输出格式为: <标识符>

    slots:
      city:
        description: 城市
        prompt: |
          当前正在执行Action {current_form_name}, 其描述为 {current_form_description}。
          接下来需要询问用户，需要查询哪个城市的天气。

      time:
        description: 时间
        prompt: |
          当前正在执行Action {current_form_name}, 其描述为 {current_form_description}。
          接下来需要询问用户，需要查询哪天的天气。

    executer:
      url: https://my-json-server.typicode.com/CotaAI/cota-api/posts/3
      methold: GET

```
注意：Cota提供了丰富的mock api供开发者快速测试新建的对话，同时开发者也可以在CotaAI的cota-api仓库中提交自己mock的api。

### CustomAction
在业务场景中，我们常用的是自定义Action，如计算器功能、查天气等，都需要自定以Action,自定以Action非常简单，只需要在task.yml中配置，这些自定以的Action会自动注册到智能体中。

#### 自定义基础类型的Action
如果你不想使用Response,想自己定义一个Action名字，用于回答用户的问题，你可以如下配置，并在配置删掉原Response（如果担心引起歧义）。事实上，鉴于使用prompt的灵活性，在当前
版本中，自定义基础类型的Action是没必要的，完全可以通过修改prompt使用同样的效果。

##### 配置示例

```yaml
actions:
  ResponseMy:
    description: "回复用户的提问"
    prompt: |
      根据任务描述和历史对话，生成回答。

      任务描述:
      {task_description}

      历史对话:
      {history_messages}

      输出格式为: <回答用户的话>

```

#### 自定义Form类型的Action
更常见的是自定义Form类型的 Action，如查询天气、订餐或者定机票。

##### 配置示例
```yaml
actions:
  Weather:
    description: "查询天气"
    prompt: |
      当前正在执行{current_form_name}, 其描述为{current_form_description}。将计算结果返给用户,注意: 严格按照计算结果返还用户，不要自己计算。
      输入:
      {current_form_slots_state} 
      计算结果为
      {current_form_execute_result}

    updater:
      description: "更新状态"
      prompt: |
        当前正在执行{current_form_name}， 其描述为{current_form_description}。根据对话内容及Action序列，结合当前slot的状态，填充或重置slot的值。
        
        历史Action序列为:
        {history_actions_for_update}

        Action的描述为:
        {action_descriptions}

        当前slots为:
        {current_form_slots_state}

        slots的含义为:
        {current_form_slots_description}
        
        填充或重置slot的值, 保持slots格式输出json字符串。

    breaker:
      description: "判断是否跳出"
      prompt: |
        当前正在执行{current_form_name}， 其描述为{current_form_description}。根据对话内容，结合用户最近的对话，判读用户意图，决定是否跳出当前Action.

        对话内容:
        {history_messages}

        用户最后对话：
        {latest_user_query}

        如果当前用户意图和{current_form_name}无关，则跳出当前Action, 输出标识符true。
        如果当前用户意图和{current_form_name}有关，则维持当前Action, 输出标识符false。

        输出格式为: <标识符>

    slots:
      city:
        description: 城市
        prompt: |
          当前正在执行Action {current_form_name}, 其描述为 {current_form_description}。
          接下来需要询问用户，需要查询哪个城市的天气。

      time:
        description: 时间
        prompt: |
          当前正在执行Action {current_form_name}, 其描述为 {current_form_description}。
          接下来需要询问用户，需要查询哪天的天气。

    executer:
      url: https://my-json-server.typicode.com/CotaAI/cota-api/posts/3
      methold: GET

```
