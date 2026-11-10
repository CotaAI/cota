# Policy 配置

Bot 自动加载 `policy/` 目录下的 `.yml` / `.yaml` 文件。文件直接使用运营编写的格式：

```yaml
policies:
  - name: 查询天气时确认城市
    steps:
      - user: 帮我查一下天气
      - bot:
          - thought: 用户需要天气服务，选择 weather。
          - skills: [weather]
          - thought: 缺少城市时先追问，话术保持简短。
          - reply: 你想查询哪个城市的天气？
      - user: 北京
      - bot:
          - thought: 城市已明确，继续查询，不重复询问。
          - skills: [weather]
          - result: 查询成功，返回北京气温 22°C，来源 wttr.in，观测时间 09:00 AM。
          - thought: 按真实返回的数据说明温度、来源和观测时间，不能照抄案例数值。
          - reply: 北京当前气温 22°C；来源 wttr.in，观测时间 09:00 AM。
```

## 契约

- 文件只有 `policies` 顶层键，值为列表。空列表表示没有案例。
- 每条 Policy 只有 `name` 和 `steps`；名称为非空文本，在全部加载文件中唯一。
- 每个外层步骤只有 `user` 或 `bot`。`user` 是非空文本；`bot` 是非空有序列表。
- 每个 Bot 列表项只有 `thought`、`skills`、`result` 或 `reply` 中的一个字段。
- `thought`、`result`、`reply` 是非空文本；`skills` 是非空且无重复的 Skill 名称列表。`result` 不接受对象、列表、数值或布尔值作为字段值。
- 同一个 Bot 可以有多个 thought、skills、result 和 reply 列表项。同一 Skill 可以在不同列表项中再次出现。
- 至少包含一个 Bot 步骤；只写 thought、只写 reply、Bot 主动开场、连续 Bot 步骤均可。
- 不再接受旧的 `schema_version/cases/stage/when/guidance` 或消息范围标注格式。

多个 thought 必须是独立列表项；不能在同一个映射内重复键。解析器会拒绝重复 YAML 键，避免内容被覆盖。未知字段、名称重复和格式错误均明确报错。

`skills` 使用 Pi 目录中的 Skill 名称。Pi 发现能力后，Cota 在首次模型请求前检查全部引用；未知名称会使该次运行失败。离线文件校验只检查格式，不重新实现 Pi 的 Skill 发现。

## thought 的运行语义

Cota 按原顺序渲染整个示例。每段 thought 关联同一 Bot 内后面的第一个 skills 或 reply 项，作为主要指导对象；跳过 result，因为观察结果不是 Bot 行为。没有后续行为时标为 continuation。多个连续 thought 可以指导同一个行为。它们依然是整段业务上下文的一部分，位置不构成强制执行门禁。

每次 Pi 准备模型请求时，Cota 提供独立的业务指导文本，包含示例用户表达、Bot 内的判断与行为顺序，以及明确的示例边界。模型结合真实对话及工具结果判断案例是否适用、当前走到哪里。不会把 thought 伪装成模型自己的 reasoning，也不会将示例用户消息、回复加入真实历史。

## result 的运行语义

`result` 是可选的自然语言观察，用来描述这个案例假设遇到的结果。通常写在 skills 后、后续 thought 或行为前；它不定义 Skill 的返回类型，也不要求为每个 Skill 穷举结果。只覆盖会改变后续处理的关键分支，例如查询成功、未找到、服务异常、数据不完整。

不同分支分别写成命名 Policy。需要分别表达多个 Skill 的结果时，拆成 `skills → result → thought → skills → result`，不要依赖隐式的工具调用归属。格式不强制每次 skills 都有 result，也不把顺序解释为自动执行程序。

渲染时使用 `Result（示例结果条件）` 标签。模型须根据真实执行证据判断分支是否适用；读取 Skill 不代表已执行，查询失败不等于没有数据。没有实际结果或结果无法确认时，应补充查询、澄清或说明无法确认，不能用案例结果补齐事实，也不能把不同案例的结果拼成一次执行。

result 保留在 Policy 和标注数据中，不生成工具消息、ToolResultEvent 或 Skill 完成事件。当前不会自动提取结果、选择结果分支或增加结果枚举；工具原始输出仍独立保存在 Trace 中。没有 result 的原有案例继续有效。

没有基于案例的确定性状态机或自动分支执行。可配置 BM25、Embedding 或模型等 Policy 方法选择指导，工具继续负责权限与硬约束。Skill 读取证明获得说明，不证明业务执行完成。

## 策略与训练

`policy/` 保存运营案例；`agent.yml` 的 `policy.type` 配置运行方法。支持 all（默认）、bm25、embedding、model、retrieval_model、search_model、rule，以及自定义 Policy 类。

```yaml
policy:
  type: bm25
  artifact: models/policy.json
  max_policies: 4
  max_chars: 8000
  options:
    top_k: 12
```

```bash
cota train --config bots/weather
cota train --config bots/weather --check
```

除 all 外，先 train 再加载 Bot。案例或策略 options 更新后需要重训；产物不匹配时明确失败，不静默使用旧索引。完整生命周期、模型/向量资源和自定义类见 [可训练的 Policy](../concepts/trainable-policy.md)。

## 预算和 Trace

`agent.yml`：

```yaml
policy:
  max_policies: 8
  max_chars: 12000
```

预算为正整数。只考虑其引用 Skill 全部可用的案例（不引用 Skill 的话术/原则案例同样支持）。默认 all 优先考虑涉及当前模型上下文中成功读取 Skill 的案例，其他案例随后；同组保留文件名及文件内顺序。其他策略使用当前对话和工具观察进行选择；结果不表示业务已完成。

没有关注步骤时加入完整案例。选择结果指定 `step` 时，只注入截至该步的示例对话、能力顺序和 result 条件，以及当前步的 thought；保留前文回复中的问题与条件，让“是的”等简短用户回答仍可理解，不带入后续无关对话和较早步骤的 thought。来源哈希仍对应完整标注，Debug thoughts 对应实际注入步骤。字符预算包括统一指导说明、标题与分隔符。单条完整案例超限时加载报错；组合超限记录省略原因并继续考虑后续案例。上下文压缩后重新计算读取关联与排序，active_skill 和历史读取不能替代当前保留的成功结果。

`bot_utter.payload.llm.policy` / `tool_started.payload.llm.policy` 保存本次实际注入案例的名称/内容哈希、策略类和版本、配置与训练状态哈希、有效 read_skills，以及选择状态、步骤、证据 ID。它是实际选择的记录，不表示案例的示例结果真实发生。

Debug 模式下，独立模型诊断的 preparation 保存完整选择理由、thought、预算省略项、缓存命中与耗时；最终 request 保存实际 system prompt 和工具声明。完整案例不重复写入每个核心事件。

Trace 中的位置从 0 开始，仅供开发和审核；运营不用填写索引。

文件更新后需重新加载 Agent；训练型策略先重新 train。all 在目录不存在时为空 Policy；修改文件不会自动影响已经加载的实例。完整填写和导出流程见 [对话标注与 Policy](../concepts/skill-policy.md)。
