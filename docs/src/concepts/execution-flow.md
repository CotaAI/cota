# 一轮对话如何执行

Cota 保存输入、执行事实和会话上下文；Pi Agent Core 决定本轮何时请求模型、调用工具以及结束。Python 侧没有第二套模型—工具循环。

## 从输入到回复

1. Channel 或应用提交带身份、会话标识和 `message_id` 的输入。Store 检查重复输入与冲突；Application 在确认接收前保存 user_utter，同一会话的执行受顺序调度和持久化版本约束。
2. Processor 从已保存的触发输入构造本轮上下文视图，刷新当前用户记忆。后续输入可继续落库，但不混入本轮。群聊由 Application 管理参与决策与触发输入；低层 Processor 的独立 shell/评测入口仍自行保存输入。
3. Cota 追加并提交 `run_started`，把 DST 的工作上下文副本传给本轮 Pi worker；图片以不可变资源引用传输，原始证据保留在 Cota。
4. Pi 发现该 Bot 的 Skill 资源。Cota 保存本轮资源目录和执行环境到 run metadata；发现阶段不执行 Policy 检索。
5. 每次模型请求前，Pi 调用 Cota 的 `prepare`，提供已提交工作投影、请求专用运行时信息和工具 schema。Policy 与 Knowledge 由模型按需调用工具查询。Pi 适配层随后检查 token、请求体积和图片预算，必要时使用官方组件压缩；Cota 提交压缩事件并重新准备投影后，再由 Node 中的 Pi 官方 provider 直接请求已配置的 LLM。Python 专用 custom/RAG 端点保留其适配器。
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

如果上一轮仍是 `running`，Application / Processor 先经 Store 检查执行者归属。本机 SQLite 只有在原主机与 Store 作用域匹配、取得独占执行锁时才补记中断，再处理新输入；Pi 子进程继承锁，Python 退出不会提前允许接管。无法验证归属或原执行者仍存活时抛出 `RunInProgress`。查询和重复输入不会触发恢复，旧工具不自动重试，详见 [恢复边界](dst.md#恢复与不兼容处理)。

## 两层上下文

Cota 的模型上下文由事件增量投影而来，并包含在快照中。恢复时从有效快照加后续事件得到同样状态；事件重放不访问模型、工具或实时记忆。

Pi 只持有本轮暂态上下文。每次 `prepare` 由 Cota 从已提交 DST 生成消息投影，原生 Node 与 Python 自定义适配器均使用它；不从 Node 反传整份历史。固定 system、Skill 目录、工具指南和执行环境保持稳定，记忆与群聊触发信息作为请求专用 runtime_context 通过 Pi 的转换接口进入请求，不成为新的 user_utter。Knowledge / Policy 查询则保存为真实工具结果，当前 run 保留全文，后续 run 可使用带真实返回数量的查询摘要；完整证据继续保存在 Store。详见 [Pi runtime](pi-runtime.md#稳定-system-与本次请求指导)。

每次模型请求前，Node 适配层复用 Pi 的 `estimateTokens`、`shouldCompact`、`findCutPoint` 和 `compact`，结合实际供应商 usage 检查 token 预算。图片采用 Pi 的独立估算，不按 Base64 字符数计算；工具定义和临时指导也计入预算。usage 推导预算会保守预留当前 system/工具大小，可能提前压缩，不代表精确计费。超过工作触发阈值（默认 64000，并受模型容量减预留 token 约束）时，Pi 选择安全切分点并生成摘要，支持在同一个用户任务中切分，保留最近的工具调用与结果配对。普通 openai 端点的摘要请求也通过 Node 中的 Pi 官方 provider 发出，不向用户流式展示摘要；输出使用独立的 `compaction.max_tokens`，默认 `min(8192, reserve_tokens)`，不受主回复默认 500 tokens 限制；摘要输入本身过大时在调用供应商前拒绝。

Cota 在启动、prepare 和压缩恢复边界用不可变引用替换历史图片；Node 在预算检查前按需加载本次图片证据，并通过 Pi 的公开 `transformContext` 钩子交给模型：最新用户输入图片和当前完整工具批次保留像素，相同字节只发送一次；较早图片替换为包含消息或附件 ID、已知资源路径、已知内容 SHA-256 和重新读取说明的引用。工具结果的简短图片引用置于原始长文本之前，避免 Pi 摘要截断时丢失来源。同一路径更新后按实际图片字节区分版本；新的显式读取仍可带回像素。已有文字观察照常保留，图片读取或引用均不表示审校通过。该选择只影响工作消息和模型请求，DST、原始事件和图片保持完整；恢复后重新计算选择。需要复查时，Pi 官方 read 工厂通过 Operations 接口加载本会话的精确旧版本，即使工作文件已被覆盖；虚拟资源路径并非磁盘文件。附件也在预算前按需加载，避免发送边界重新补回旧像素。

Cota 同时检查序列化体积（默认 32 MiB）、图片数量（默认8张）和图片解码后总字节（默认16 MiB），分别使用 `dialogue.compaction.max_request_bytes`、`max_images`、`max_image_bytes` 配置。图片选择后的当前输入或工具批次仍超过图片预算时明确报错。token 或整体字节超限时继续由 Pi 选择安全切点和生成摘要，保留工具调用与结果配对；摘要仅根据已有文本证据，保留资源位置供需要时重新读取。图片投影改变后不能沿用包含旧像素的 usage；投影稳定并取得新响应后恢复使用真实 usage。助手来源保存一个小型 image_projection 指纹（模型标识与图片可见版本），从事件恢复时同样可校验，不重复保存历史或图片。

Cota 验证替换范围是当前上下文的准确前缀，保存 `context_compaction` 并提交 Store，再从 DST 重新准备工作投影。原始事件不删除；无须 AgentSession 或 Pi 会话文件。空摘要、截断、取消、提交失败时不继续模型/工具执行；无法缩减的单条输入或最近工具批次明确报错。旧摘要前的 usage 不用于新的上下文预算。模型容量优先来自 `endpoints.yml` 的 `context_window`，其次是 Pi 内置目录；未知型号使用标记为 fallback 的 65,536 token 运行预算，部署者可按供应商确认值覆盖。

实现入口：`cota/processor.py`、`cota/runtime/pi_runtime.py`、`cota/runtime/pi/engine.mjs`、`cota/runtime/pi_trace.py`。

相关文档：[DST 与 Store](dst.md) · [Pi runtime](pi-runtime.md) · [Skill 与 Policy](skill-policy.md) · [可靠投递](../deployment/delivery.md)

原生主模型请求的上下文溢出由 Pi `isContextOverflow` 识别。第一次溢出仅作为失败模型诊断保存，不变成 Bot 回复或工具事实。尚有决策预算时，Cota 的 Node 适配层让当前 Pi 调用结束，省略未提交的失败响应，再调用一次 Pi continuation；其 prepare 阶段强制使用同一套 Pi 压缩组件。Store 确认压缩提交后才允许下一次模型请求。重复溢出、取消、预算耗尽或提交失败时结束，不自动重放工具。压缩原因及压缩前预算记在现有 context_compaction 中；不增加 Event 类型。
