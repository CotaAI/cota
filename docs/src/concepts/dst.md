Dialogue State Tracker (DST) 是多轮对话系统中的一个关键组件，负责跟踪和更新对话状态。DST 在多轮对话中扮演着“记忆”的角色，它记录了对话的历史信息，帮助系统理解当前对话的上下文。

## 基本结构
DST最重要的属性是Action列表，维护着整个Action执行顺序及其执行结构，包括智能体的Action和用户的Action。通过DST中的Action序列和task.yml配置中关于agent和Action的定义，可以完整复现出一个对话过程。
在当前轮的对话结束后，DST会执行序列化操作，并将序列化的结果保存到如`mysql`数据库中。在下一轮对话中，当智能体接收到用户的`message`后，第一步就是
从数据库中得到序列化的Action列表，复现上一轮的对话状态，在此基础上进行状态的更新和Action的选择与执行。

DST提供多种state，来帮助agent观察当前对话状态，更好的理解上下文以及完成整个对话。这些state主要用在prompt提示词中，通过`{}`来区分，
如 `{task_description}` 代表对当前task的描述，在执行`Response`时，action会从dst中获取state - task_description, 并将其拼接到prompt中，
这对提升回复的质量非常重要。

在task.yml中使用DST中state的示例：
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

      请回答用户

```


Cota官方会从不同维度，提供和维护多种方法，以支持Cota能应对不同的场景。这些DST的方法将会在本文档中维护和更新。

## state 列表

### task相关的state

**task_description**
* 描述：
* 返回示例：


### user相关的state

### action相关的state

**current_action_name**
* 描述：
* 返回示例：

**current_action_description**
* 描述：
* 返回示例：

**latest_action_name**
* 描述：
* 返回示例：

**latest_action_description**
* 描述：
* 返回示例：

**latest_action_result**
* 描述：
* 返回示例：

**latest_user_query**
* 描述：
* 返回示例：

**action_names**
* 描述：
* 返回示例：

**action_descriptions**
* 描述：
* 返回示例：

**bot_action_names**
* 描述：
* 返回示例：

**bot_action_descriptions**
* 描述：
* 返回示例：

**action_names_no_selector**
* 描述：
* 返回示例：

**action_descriptions_no_selector**
* 描述：
* 返回示例：

**action_names_for_selector**
* 描述：
* 返回示例：

**action_descriptions_for_selector**
* 描述：
* 返回示例：

**bot_action_names_no_selector**
* 描述：
* 返回示例：

**bot_action_descriptions_no_selector**
* 描述：
* 返回示例：

**bot_action_names_for_selector**
* 描述：
* 返回示例：

**bot_action_descriptions_for_selector**
* 描述：
* 返回示例：

### action序列相关的state

**history_messages**
* 描述：
* 返回示例：

**history_actions**
* 描述：
* 返回示例：

**history_action_names_and_results_fiter_empty**
* 描述：
* 返回示例：

**history_action_names_and_descriptions_and_result**
* 描述：
* 返回示例：

**history_action_names_and_descriptions_and_result_filter_empty**
* 描述：
* 返回示例：



### form相关的state

**current_form_name**
* 描述：
* 返回示例：

**current_form_description**
* 描述：
* 返回示例：

**current_form_execute_result**
* 描述：
* 返回示例：

**current_form_slot_names**
* 描述：
* 返回示例：

**current_form_slot_descriptions**
* 描述：
* 返回示例：

**current_form_slot_states**
* 描述：
* 返回示例：

**current_form_messages**
* 描述：
* 返回示例：


