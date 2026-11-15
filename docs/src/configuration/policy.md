# Policy 配置

Policy 是供模型查阅的业务案例。Cota 在加载 Bot 时建立本地 BM25 索引，注册 `policy_guidance` 工具；Pi 驱动的模型决定何时查询、如何参考，不在每次模型请求前自动注入案例。

## POLICY.md

在 Bot 的 `policy/POLICY.md` 中编写：

```markdown
---
name: support-policy
description: 天气查询、澄清与失败处理的业务策略
top_k: 5
---

## weather-unavailable

- User: 北京现在多少度？
- Bot:
  - Skills: weather
  - Result: 主服务和备用服务均未返回可信天气数据。
  - Thought: 说明当前无法确认，不猜测温度，也不把服务失败说成城市不存在。
  - Reply: 暂时没查到北京的气温，稍后再试一下吧。
```

frontmatter 的 `name`、`description` 为必填非空文本；`description` 进入工具说明，帮助模型判断是否查阅。`top_k` 是正整数，默认 5，表示最多检索的候选案例数量；字符预算可能使实际返回数量更少。

每个二级标题是案例名称。`User` / `Bot` 表达对话顺序；Bot 内按顺序填写 `Thought`、`Skills`、`Result`、`Reply`，不必填满所有字段。Skills 使用逗号分隔的 Skill 名称，与 Pi 目录保持一致。thought 是业务指导，result 是示例条件，均不证明实际执行或验收通过。

目录中同级的 Markdown 和 YAML 案例也会加载；YAML 使用 `policies: [{name, steps}]`，适合 `cota annotate` 的导出和审核流程。案例名称在全部文件中保持唯一。`policy/eval/` 不参与案例索引。

## 运行与记录

```text
模型调用 policy_guidance(scenario)
  → Cota 检索并渲染案例
  → 标准工具结果 content + details.hits
  → Store 保存 tool_started / tool_result
  → Pi 根据实际对话、案例和工具证据继续决策
```

`hits` 是实际返回数量，不是整个索引的命中总数。Runtime 不从正文中的“未找到”、分隔线或案例标题猜测数量。完整结果保存在事件中；下一 run 的请求可以使用查询摘要，原始证据不改写。需要重新判断时，模型可再次调用检索工具。

Policy 不改变工具权限，不是自动业务状态机。检索工具默认注册；可用 `tools.deny: [policy_guidance]` 显式禁用。Skill 的发现、选择与工具执行继续通过 Pi 完成。

修改文件后重新加载 Agent 即重建索引。不需要 `agent.yml.policy.type`、训练产物或 `cota train`。

相关文档：[对话标注](../concepts/skill-policy.md) · [Policy 检索](../concepts/trainable-policy.md) · [Pi runtime](../concepts/pi-runtime.md)
