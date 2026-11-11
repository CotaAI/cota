# DST 与 Store：会话事实和恢复

DST（Dialogue State Tracker）保存一个 `session_id` 的事件派生状态。Store 保存事实、快照、run metadata 和投递数据。Agent、模型连接、数据库连接不属于会话状态。

## 事件与状态的关系

实时执行和历史恢复共用 `DST.apply_event()` reducer。它校验事件格式、顺序、引用和 run 状态转移；重放只推导状态，不调用工具、模型、时钟或用户记忆。

| 事件 | 状态变化 |
| --- | --- |
| `user_context_updated` | 在同一事件中记录身份与当时上下文；身份或内容变化时更新 `user_id` / `user_context` |
| `user_utter` / `bot_utter` | 更新最近输入 / 回复游标，进入对话与模型上下文投影 |
| `run_started` | 建立 `execution`，记录 run、触发输入、引擎、状态和 pending tools |
| `run_finished` | 更新本轮执行结果，如 `completed`、`failed`、`interrupted` |
| `tool_started` / `tool_result` | 更新当前 run 的 pending tools，投影工具调用与结果；成功 Skill 阅读更新 `active_skill` |
| `context_compaction` | 在模型上下文投影中用摘要替换指定历史消息，不删除原始事实 |

`state_dict()` 的核心字段为 `user_id`、`user_context`、`active_skill`、`execution`、`context_messages`，另有 `created_at`、`updated_at` 和最近用户 / Bot 事件 ID。它不包含完整事件列表、Agent 或数据库 revision；revision 是 Store 的并发元数据。

`active_skill` 仅记录最近成功读取的 Skill。它不是业务意图、执行栈、权限、当前 SOP 步骤或“Skill 已完成”的判断。历史或其他 run 的工具观察可以作为 Trace 事实保留，但不能改变当前运行的 pending tools。

## Event envelope 与 payload

所有事件共用一个 envelope，业务字段放在 `payload` 中。例如一条最小用户输入事件：

```json
{
  "schema_version": 1,
  "event_id": "input-example-001",
  "sequence": 1,
  "timestamp": 1793836800.0,
  "run_id": null,
  "type": "user_utter",
  "source": "cota",
  "payload": {"text": "你好"}
}
```

`event_id` 是稳定身份，`sequence` 是会话内从 1 开始的顺序；`run_id` 关联执行，输入可不属于某个 run。`source` 表示事实来源，例如 `cota` 或 `pi`；`timestamp` 为事件时间。真实接入还会在输入 payload 的 metadata 中保存 `message_id`、发送者和平台信息。

工具参数位于 `tool_started.payload.arguments`，原生结果和状态位于 `tool_result.payload.result/status`；模型可见内容需要与原生结果区分时记录在 `payload.content`。参数转换改变了模型原提案时，开始事件另存 `payload.requested_arguments`。事件之间通过 tool call ID、run ID 和模型来源事件引用建立关系，不能随意拼接或修改已提交事实。

DST 对外返回事件、上下文和状态副本。状态更新必须经过 reducer；内部已应用事实和上下文不可变，运行提交检查状态及事件游标，避免为了检查旧图片而反复恢复整段历史。

## SQL 数据如何组织

`Store.create()` 支持内存和 SQL 后端。内存后端适合临时运行；SQLite 或其他支持的 SQL dialect 用于跨重启保存。

| SQL 表 | 职责 |
| --- | --- |
| `sessions` | 会话元数据：用户索引、revision、最后 sequence、完整事件流哈希和更新时间 |
| `events` | 一行一个事件；主键为 session + sequence，payload 为 JSON，event ID 在会话内唯一 |
| `session_snapshots` | 每个会话的最新状态快照、覆盖到的 sequence |
| `run_metadata` | 按 session + run 保存不可变资源来源，例如本轮可用 Skill 目录 |
| `model_debug` | 可选模型诊断的可变状态、计时与索引；不作为对话事实来源 |
| `model_debug_bodies` | 按请求与字段保存大请求正文、准备详情和响应，读取时合并为完整诊断 JSON |
| `deliveries` | 指向已提交 `bot_utter` 的可变投递状态、尝试次数和重试时间 |

用户长期记忆由独立的 UserMemory 后端 / `user_memory` 表保存；它按用户而非会话组织。刷新到某次对话的内容通过 `user_context_updated` 记录，历史恢复不会重新查询实时记忆。Skill 目录元数据同样不冒充一条对话发言。

Store 使用 revision、事件前缀和执行版本校验拒绝陈旧写入，并提供进程内会话锁。回复事件和对应投递 outbox 可以在一次提交中保存；发送失败可重试投递，不需再次执行模型和工具。Channel 收到通知不等于用户已收到消息。

## 快照保存什么

Store 在 run 结束或距上次快照达到事件间隔时建立快照。间隔默认 100，由 `base_store.snapshot_interval` 调整。快照的 `data` 包含：

| 字段 | 含义 |
| --- | --- |
| `session_id` | 所属会话 |
| `schema_version` | DST 状态格式版本，当前 `DST.STATE_VERSION` 为 11；不同于事件 envelope 的版本 1 |
| `last_sequence` / `last_event_id` | 快照覆盖的事件前缀末端 |
| `events_hash` | 所覆盖事件前缀的规范 JSON 哈希 |
| `state` | 上述 `state_dict()` 结果，包括增量投影的 `context_messages` |
| `created_at` | 快照创建时间；不同于 `state.created_at` 的会话时间 |
| `checksum` | 对除 checksum 外整个快照内容计算的哈希 |

`context_messages` 保留模型响应与工具结果之间的稳定关联，供下一轮 Pi 初始化。当前请求的 system prompt、Skill 目录和 Policy guidance 由 `prepare` 动态加入，不作为固定指令混入历史投影。上下文压缩只改变这一投影，完整原始事件仍保留。交给 Pi 的传输副本另把图片换成不可变资源引用，避免启动或恢复时携带全部历史 Base64；这不会回写或精简 DST，详见 [Pi runtime](pi-runtime.md#图片证据与工作上下文)。

## 恢复与不兼容处理

`Store.load()` 一致读取会话元数据、事件、快照和 run metadata，先验证事件数量与完整事件流哈希。当前 SQL 实现仍读取并校验完整事件流；使用快照节省的是 reducer 的前缀回放，不代表数据库只读取尾部。

快照格式、checksum、事件前缀哈希、游标和状态校验均通过时，DST 装入快照状态，只对 `last_sequence` 之后的事件执行 reducer。没有快照、JSON 损坏、旧状态版本或其他快照校验失败时，丢弃这份缓存并全量回放事件。源事件格式、引用或完整性损坏仍会报错，不能靠忽略快照掩盖。

快照不兼容与数据库表结构不兼容是两回事。SQLStore 初始化会检查已有表缺失的列，发现不兼容时明确报错，不自动迁移旧表。快照回放能恢复派生状态，不能替代数据库 schema 迁移。

如果已保存的 execution 仍为 `running`，新 runtime 抛出 `RunInProgress`。恢复方必须先确认旧执行者已停止，取得独占会话所有权，再重新读取最新状态，为同一个 run 追加 `run_finished`，payload 为 `{"status": "interrupted"}`，并通过 Store 提交。进程内会话锁不等于跨进程独占；不要仅因超时就宣告另一执行者已退出。

恢复只追加中断事实，不自动重放 pending tools。若工具副作用已经发生但结果未提交，需要检查外部系统再决定补偿或新任务；本地状态恢复不提供外部操作的 exactly-once 保证。

## 查询

```python
tracker = await agent.store.load("alice-demo", agent=agent)
print(tracker.execution)
messages = await agent.store.history("alice-demo")
events = await agent.store.events("alice-demo", after_sequence=0, limit=100)
```

这些查询用于应用或受信任的诊断代码；不存在的会话 `load()` 返回 `None`。面向用户的 Web 历史只暴露对话消息，不直接导出原始工具结果和 debug 数据。输入 `message_id` 用于去重；同一标识携带不同内容或身份会被视为冲突。

实现入口：`cota/dst.py`、`cota/store.py`、`cota/events/event.py`、`cota/events/context.py`、`cota/snapshots.py`、`cota/delivery_store.py`。

相关文档：[执行流程](execution-flow.md) · [Message](message.md) · [用户记忆](../components/user_memory.md) · [Endpoints 配置](../configuration/endpoints.md) · [可靠投递](../deployment/delivery.md)

## 运行中的增量提交

`apply_event()` 验证新事实、更新派生状态，并增量推进事件前缀的规范 JSON 哈希。运行时 `Store.save()` 只序列化未提交事件，在事务中检查 revision、已保存前缀和不可变 run metadata，追加事件及相应 outbox。没有新事实或资源元数据时不写入，也不增加 revision。普通提交不读取旧快照或恢复整个 DST。

隔离执行通过 `save_execution()` 合并回主会话：同一执行生命周期内复用已验证的会话与提交游标，revision 改变时重新加载，因而不会覆盖期间收到的新输入。缓存随执行对象释放；进程重启仍从数据库恢复。原始事件和现有哈希格式不变，运行结束及事件间隔的快照规则继续生效。`load()`、导出及按需状态检查仍完整验证已保存事件，不能用运行时缓存代替恢复校验。

模型诊断的大字段保存在独立的 `model_debug_bodies` 表，按会话、请求和字段定位；`model_debug` 保存可更新的状态、计时与索引。正文写入一次，适配器输入可升级为实际供应商请求；后续状态与 Event 关联更新不重复写图片正文。读取时合并成原来的完整诊断 JSON。该表首次打开数据库时创建，不需要删除现有会话数据库，也不参与 DST 恢复。
