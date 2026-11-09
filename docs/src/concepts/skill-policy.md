# 对话标注与 Policy

Cota 以 Skill 定义业务能力，以 Trace 保存执行证据，以围绕 Skill 的业务流程标注沉淀 Policy，再用 Policy 改善后续 Skill 的选择、组合与执行。

两种来源使用完全相同的文件格式：运营可以直接编写期望对话，也可以修改真实对话整理出的草稿。无需消息编号范围、意图总结、阶段标签或执行事件 ID。

## 像写对话一样标注

```yaml
policies:
  - name: 查询天气时确认城市
    steps:
      - user: 帮我查一下天气
      - bot:
          - thought: 用户需要天气服务，应选择 weather。
          - skills: [weather]
          - thought: 用户还没提供城市，先询问，追问简短自然。
          - reply: 你想查询哪个城市的天气？
      - user: 北京
      - bot:
          - thought: 已补充城市，继续查询，不再重复询问。
          - skills: [weather]
          - thought: 查询成功时说明真实结果和来源；失败时明确说明，不编造。
```

`name` 用于管理案例；`steps` 表达对话顺序。`user` 是用户的具体表达，`bot` 是机器人在这个位置的处理过程，其内部是一个有序列表：

| 字段 | 填写内容 |
| --- | --- |
| thought | 业务判断、条件、异常处理或话术原则 |
| skills | 期望使用的业务能力，按期望顺序排列 |
| result | 案例假设观察到的执行结果，供判断后续分支；可选 |
| reply | 希望机器人说的话，是示例而非固定事实 |

每个列表项只写一个字段。同一个 Bot 中可以有多段 thought，分别放在能力选择和话术前；同一 Skill 也可以重复出现。简单案例可以只写 skills 或 reply，复杂案例再补充 thought。不必填满所有字段。

例如能力组合：`skills: [query-order, query-logistics]`。不应使用某个能力、某种情况必须先追问等规则，直接用 thought 表达，不另设判断标签。只写回复也可以：

```yaml
policies:
  - name: 礼貌结束
    steps:
      - user: 谢谢
      - bot:
          - reply: 不客气！
```

一段 thought 主要指导后面的 skills 或 reply，末尾的 thought 指导后续处理。它们仍参与整段上下文，不是严格的执行程序。`reply` 中的订单、天气等信息只是示例，真正回复必须以当前查询结果为准。

## 不同结果如何继续处理

把会改变业务处理的结果写成不同案例，使用可选的 `result` 描述观察条件，thought 说明如何判断并采取下一步。不需要预先枚举 Skill 的所有返回值：

```yaml
policies:
  - name: 天气查询成功
    steps:
      - user: 北京现在多少度？
      - bot:
          - skills: [weather]
          - result: 查询成功，返回北京气温 22°C，来源 wttr.in，观测时间 09:00 AM。
          - thought: 根据实际返回值说明温度、来源和观测时间。
          - reply: 北京当前气温 22°C；来源 wttr.in，观测时间 09:00 AM。
  - name: 天气服务不可用
    steps:
      - user: 北京现在多少度？
      - bot:
          - skills: [weather]
          - result: 主服务和备用服务都未取得有效天气数据，当前温度无法确认。
          - thought: 说明暂时无法查询，不猜测温度，也不声称城市不存在。
          - reply: 天气服务暂时无法查询，我还不能确认北京当前的温度，请稍后再试。
```

`result` 写“本案例观察到了什么”，`thought` 写“应该如何理解和处理”。例如“返回降雨信息”是结果，而“用户计划出游，需要提醒雨天安排”是业务策略。一个 Skill 可以有多个结果案例，也可以继续只用 thought 表达通用原则。

多个 Skill 的结果需要分别表达时，拆成多段 `skills → result → thought`，再写下一段 skills 或 reply。result 不是行为，thought 的主要指导对象会跳过 result，指向后续 skills 或 reply。

运行时，结果条件以明确的示例标签进入业务指导，不会成为真实工具消息。模型必须依据实际执行证据决定是否参考对应分支；结果缺失或不明确时，不能拿案例中的结果补齐。读取 Skill 也不代表业务已经完成。系统不自动选择分支，关键流程仍需用业务评测检查实际决策。

## 从零编写

把文件保存到 Bot 的 `policy/` 目录。默认 all 策略重新加载 Agent 即可；训练型策略需先执行 `cota train --config BOT`。它不需要会话或数据库，也不需要先运行一次机器人。

也可以先校验并生成供审核的文件：

```bash
cota annotate import --config bots/weather --input manual.yml --output reviewed.yml
```

此命令只处理文件，不连接 Store。它检查格式和预算，保持原有 steps/thought 顺序，输出同一套 policies 格式。Skill 名称在 Pi 发现能力后、第一次模型请求前验证。

## 从真实对话整理

```bash
cota annotate export --config bots/weather --session SESSION_ID --output review.yml
```

生成 `review.yml`，包含真实用户表达和机器人回复，供运营编辑。只生成这一个文件，不保存来源或标注版本。

运营可以修改用户表达、增删步骤、补充 thought、skills 和 result、纠正回复，也可以拆成多个命名案例。真实回复可能是错误答案，必须审核；系统不会把“读过 Skill”自动当成“应该使用该能力”，也不会把模型内部推理转换为运营 thought。工具结果条件由运营根据执行证据填写。

只有用户消息、尚无 Bot 处理的会话仍可导出草稿，运营需补充 Bot 步骤后再导入。

```bash
cota annotate import --config bots/weather --input review.yml --output reviewed.yml
```

导入只校验格式和预算并生成 Policy 文件，不读取或修改会话数据库。再次导出始终读取真实对话；已编辑的案例保存在 Policy 文件中。执行事件不保存人工标注，也不承担 Policy 修订管理。

输出文件不会覆盖已有文件。将审核后的文件放入 `policy/`；训练型策略执行 `cota train --config BOT` 后重新加载 Agent，默认 all 策略直接重新加载即可。更新同名案例时替换原 Policy 文件，避免重复加载。当前不自动发布或热更新；自动化的 event → policy 转换及写入另行设计。

独立 export CLI 需要持久 SQL Store（文件 SQLite、MySQL 等）；内存 Store 可在 Bot 进程中使用以下接口：

```python
from cota.annotation_files import export_worksheet, write_worksheet, read_worksheet

dst = await agent.store.load(session_id, agent=None)
write_worksheet("review.yml", export_worksheet(dst))

# 人工编辑后，校验并写入独立文件；不写回 Store。
write_worksheet("reviewed.yml", read_worksheet("review.yml"))
```

## Policy 怎样影响 Pi

每次模型请求前，Cota 将预算内的完整 Policy 示例放入独立的业务指导中，保留 user、thought、skills、result、reply 顺序，并标明 thought 的主要指导对象。工具执行后、用户补充信息后及恢复运行时，模型都能结合最新事实继续使用这些原则。

同一段业务指导可以同时影响能力选择、异常处理与话术。Cota 不会把示例未来的用户消息或回复当成已发生的事实，也不会把人工 thought 包装成模型已经产生的思考。

默认 all 提供有界的完整案例注入；还可配置词项、向量、模型判断或模型搜索等 Policy。训练和扩展接口见 [可训练的 Policy](trainable-policy.md)。当前保留完整案例及其条件，模型可标记关注步骤，但没有逐步骤强制执行。核心来源事件记录实际案例名称/哈希与选择状态；完整 thought 和选择诊断在 Debug preparation 中查看。结合实际 request 检查指导是否进入请求，再与真实调用、回复比较。模型决策质量仍需要业务评测，单纯“注入成功”不代表一定遵循。

标注统一使用对话式 Policy 文件，与执行事件流独立。完整配置见 [Policy](../configuration/policy.md)，持久化见 [DST](dst.md)。
