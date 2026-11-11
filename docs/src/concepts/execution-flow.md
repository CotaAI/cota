# 一轮对话如何执行

Cota 保存输入、执行事实和会话上下文；Pi Agent Core 决定本轮何时请求模型、调用工具以及结束。Python 侧没有第二套模型—工具循环。

## 从输入到回复

1. Channel 或应用提交带身份、会话标识和 `message_id` 的输入。Store 检查重复输入与冲突；Application 在确认接收前保存 user_utter，同一会话的执行受顺序调度和持久化版本约束。
2. Processor 从已保存的触发输入构造本轮上下文视图，刷新当前用户记忆。后续输入可继续落库，但不混入本轮。群聊由 Application 管理参与决策与触发输入；低层 Processor 的独立 shell/评测入口仍自行保存输入。
3. Cota 追加并提交 `run_started`，把 DST 已投影的模型上下文传给本轮 Pi worker。
4. Pi 发现该 Bot 的 Skill 资源。Cota 保存本轮资源目录和执行环境到 run metadata，并校验 Policy 引用的 Skill。
5. 每次模型请求前，Pi 调用 Cota 的 `prepare`，根据当前上下文生成 Policy guidance 和工具 schema。Pi 适配层随后检查 token、请求体积和图片预算，必要时使用官方组件压缩；Cota 提交压缩事件并重新准备指导后，再由 Node 中的 Pi 官方 provider 直接请求已配置的 LLM。Python 专用 custom/RAG 端点保留其适配器。
6. Pi 处理模型输出：执行工具后继续请求模型，或产生文字回复。Cota 持久化每个开始、结果、回复与结束事实。
7. 公开文字增量可以先作为临时预览展示；完整回复提交后才进入正式 Channel callback 或持久化投递队列，并替换预览。预览不进入 Event、历史和投递重试。传输失败可以从持久历史恢复，不能因此重新运行模型和工具。

## 工具执行的提交顺序

```text
模型提出 tool call
  → Pi 校验 / 转换参数
  → Cota 提交 tool_started；同一响应有公开文字时同时保存关联的 bot_utter
  → 已提交的公开文字进入投递
  → Cota 检查当前工具许可 / 原生执行环境
  → Pi 执行原生工具和 Node HTTP 工具，或 Cota 执行 Python 扩展工具
  → Cota 提交 tool_result
  → 返回 Pi，允许下一次模型请求
```

`tool_started.payload.arguments` 是实际交给工具的参数。只有 Pi 强制类型转换等处理改变了参数，才额外保留 `tool_started.payload.requested_arguments`。同一模型响应中的多个工具调用共享模型来源，后续调用通过事件引用关联，避免重复保存完整响应。

同一响应的公开文字不再因包含工具调用而被隐藏：关联 `bot_utter` 通过 `llm_event_id` 指向首个 `tool_started`，用于聊天展示和投递。模型上下文仍只由原始 assistant 来源投影一次，不重复添加这段文字。

未知工具、无效参数和被阻止的调用也留下开始与结果记录，但结果标识为 `blocked`。开始或结果提交失败时，不向 Pi 确认成功，后续执行停止。外部副作用与本地数据库并非同一个事务；如果副作用成功后结果保存失败，需要结合外部系统证据处理，不能盲目重放。

## 追问、完成与失败

模型直接输出问题或最终答案，Cota 先保存 `bot_utter`，再经持久化 Channel 投递。同一会话的新输入开启新 run，使用此前保存的上下文。达到迭代上限时结束为 `limited`；正常输出为 `completed`，异常为 `failed`，取消为 `interrupted`。

如果 Store 中上一轮仍是 `running`，runtime 抛出 `RunInProgress`，不会猜测执行已终止。恢复操作需要确认旧执行者停止，在独占会话的前提下记录中断；不得自动重试旧工具。

## 两层上下文

Cota 的模型上下文由事件增量投影而来，并包含在快照中。恢复时从有效快照加后续事件得到同样状态；事件重放不访问模型、工具或实时记忆。

Pi 只持有本轮暂态上下文。普通原生模型请求的 `prepare` 不传回整份历史，Cota 从自己的已提交投影计算 Policy，Node 将返回的指导应用到本轮工作上下文。每次都重新加入当前 system prompt、Skill 目录、Pi 工具使用指南、执行环境说明和业务 guidance。Policy 的“已阅读 Skill”依据仍留在模型上下文中的成功读取结果计算；最近阅读标签 `active_skill` 不能替代这一证据。

每次模型请求前，Node 适配层复用 Pi 的 `estimateTokens`、`shouldCompact`、`findCutPoint` 和 `compact`，结合实际供应商 usage 检查 token 预算。图片采用 Pi 的独立估算，不按 Base64 字符数计算；工具定义也计入预算。usage 推导预算会保守预留当前 system/工具大小，以覆盖 Policy 等指令变化，可能提前压缩，不代表精确计费。超过模型容量减预留 token 的阈值时，Pi 选择安全切分点并生成摘要，支持在同一个用户任务中切分，保留最近的工具调用与结果配对。普通 openai 端点的摘要请求也通过 Node 中的 Pi 官方 provider 发出，不向用户流式展示摘要；输出最多2000 token且不超过预留预算；摘要输入本身过大时在调用供应商前拒绝。

Cota 在预算检查前选择本次请求的图片证据，并通过 Pi 的公开 `transformContext` 钩子交给模型：最新用户输入图片和当前完整工具批次保留像素，相同字节只发送一次；较早图片替换为包含消息或附件 ID、已知资源路径、已知内容 SHA-256 和重新读取说明的引用。工具结果的简短图片引用置于原始长文本之前，避免 Pi 摘要截断时丢失来源。同一路径更新后按实际图片字节区分版本；新的显式读取仍可带回像素。已有文字观察照常保留，图片读取或引用均不表示审校通过。该选择只影响请求，Agent 工作历史、DST、原始事件和图片保持完整；恢复后重新计算选择，附件也在预算前注入，避免发送边界重新补回旧像素。

Cota 同时检查序列化体积（默认 32 MiB）、图片数量（默认8张）和图片解码后总字节（默认16 MiB），分别使用 `dialogue.compaction.max_request_bytes`、`max_images`、`max_image_bytes` 配置。图片选择后的当前输入或工具批次仍超过图片预算时明确报错。token 或整体字节超限时继续由 Pi 选择安全切点和生成摘要，保留工具调用与结果配对；摘要仅根据已有文本证据，保留资源位置供需要时重新读取。旧像素省略后的请求不能沿用包含这些像素的旧 usage 总数作为预算，会重新采用当前投影估算。

Cota 验证替换范围是当前上下文的准确前缀，保存 `context_compaction` 并提交 Store，再从 DST 投影重新准备 Policy 和上下文。原始事件不删除；无须 AgentSession 或 Pi 会话文件。空摘要、截断、取消、提交失败时不继续模型/工具执行；无法缩减的单条输入或最近工具批次明确报错。旧摘要前的 usage 不用于新的上下文预算。模型容量优先来自 `endpoints.yml` 的 `context_window`，其次是 Pi 内置目录；未知型号使用标记为 fallback 的 65,536 token 运行预算，部署者可按供应商确认值覆盖。

实现入口：`cota/processor.py`、`cota/runtime/pi_runtime.py`、`cota/runtime/pi/engine.mjs`、`cota/runtime/pi_trace.py`。

相关文档：[DST 与 Store](dst.md) · [Pi runtime](pi-runtime.md) · [Skill 与 Policy](skill-policy.md) · [可靠投递](../deployment/delivery.md)
