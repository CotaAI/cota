# 一轮对话如何执行

Cota 保存输入、执行事实和会话上下文；Pi Agent Core 决定本轮何时请求模型、调用工具以及结束。Python 侧没有第二套模型—工具循环。

## 从输入到回复

1. Channel 或应用提交带身份、会话标识和 `message_id` 的输入。Store 检查重复输入与冲突；Application 在确认接收前保存 user_utter，同一会话的执行受顺序调度和持久化版本约束。
2. Processor 从已保存的触发输入构造本轮上下文视图，刷新当前用户记忆。后续输入可继续落库，但不混入本轮。群聊由 Application 管理参与决策与触发输入；低层 Processor 的独立 shell/评测入口仍自行保存输入。
3. Cota 追加并提交 `run_started`，把 DST 已投影的模型上下文传给本轮 Pi worker。
4. Pi 发现该 Bot 的 Skill 资源。Cota 保存本轮资源目录和执行环境到 run metadata，并校验 Policy 引用的 Skill。
5. 每次模型请求前，Pi 调用 Cota 的 `prepare`。Cota 根据当前上下文生成 Policy guidance、必要时压缩历史、重新计算工具 schema，然后请求已配置的 LLM。
6. Pi 处理模型输出：执行工具后继续请求模型，或产生文字回复。Cota 持久化每个开始、结果、回复与结束事实。
7. 已提交的回复才进入 Channel callback 或持久化投递队列。传输失败可以从历史恢复，不能因此重新运行模型和工具。

## 工具执行的提交顺序

```text
模型提出 tool call
  → Pi 校验 / 转换参数
  → Cota 提交 tool_started
  → Cota 检查当前工具许可 / 原生执行环境
  → Pi 执行原生工具和 Node HTTP 工具，或 Cota 执行 Python 扩展工具
  → Cota 提交 tool_result
  → 返回 Pi，允许下一次模型请求
```

`tool_started.payload.arguments` 是实际交给工具的参数。只有 Pi 强制类型转换等处理改变了参数，才额外保留 `tool_started.payload.requested_arguments`。同一模型响应中的多个工具调用共享模型来源，后续调用通过事件引用关联，避免重复保存完整响应。

未知工具、无效参数和被阻止的调用也留下开始与结果记录，但结果标识为 `blocked`。开始或结果提交失败时，不向 Pi 确认成功，后续执行停止。外部副作用与本地数据库并非同一个事务；如果副作用成功后结果保存失败，需要结合外部系统证据处理，不能盲目重放。

## 追问、完成与失败

模型直接输出问题或最终答案，Cota 先保存 `bot_utter`，再经持久化 Channel 投递。同一会话的新输入开启新 run，使用此前保存的上下文。达到迭代上限时结束为 `limited`；正常输出为 `completed`，异常为 `failed`，取消为 `interrupted`。

如果 Store 中上一轮仍是 `running`，runtime 抛出 `RunInProgress`，不会猜测执行已终止。恢复操作需要确认旧执行者停止，在独占会话的前提下记录中断；不得自动重试旧工具。

## 两层上下文

Cota 的模型上下文由事件增量投影而来，并包含在快照中。恢复时从有效快照加后续事件得到同样状态；事件重放不访问模型、工具或实时记忆。

Pi 只持有本轮暂态上下文。每次 `prepare` 都重新加入当前 system prompt、Skill 目录、Pi 工具使用指南、执行环境说明和业务 guidance。Policy 的“已阅读 Skill”依据仍留在模型上下文中的成功读取结果计算；最近阅读标签 `active_skill` 不能替代这一证据。

超出 `context_max_chars` 时，Cota 只摘要完整的较早用户轮次，保留当前轮及未完成工具批次。压缩记录为 `context_compaction`；Store 原始历史不删除。当前轮本身仍过大或摘要失败时，本轮报错，不静默截断证据。

实现入口：`cota/processor.py`、`cota/runtime/pi_runtime.py`、`cota/runtime/pi/engine.mjs`、`cota/runtime/pi_trace.py`。

相关文档：[DST 与 Store](dst.md) · [Pi runtime](pi-runtime.md) · [Skill 与 Policy](skill-policy.md) · [可靠投递](../deployment/delivery.md)
