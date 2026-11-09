# 回复投递与恢复

Bot 执行完成和渠道送达是两件事。Cota 先生成并保存 bot_utter，再发送它；补发读取已有回复，不能重新执行模型或工具。

## 存储和职责

```text
Processor / Pi 生成 bot_utter
  → Store 同一事务保存 Events + deliveries
  → DeliveryDispatcher 查询待发送回复
  → Channel.send（稳定的 event_id）
  → Store 更新投递状态
```

DST 仍只维护对话和执行事实，没有新增 delivery Event。Store 的 deliveries 表是可更新的传输记录，包含 session_id、event_id、sequence、channel、scope、chat_id、status、attempts、next_attempt_at、error_type 和排序 ID。正文从原始 bot_utter 获取，不复制一份。

SQLStore 在现有数据库自动创建缺失的 deliveries 表，不需要额外数据库。已有 Events 不回填待发送记录，避免升级时把历史回复全部发出去。SQLite 等持久化后端能跨进程恢复；MemoryStore 只能在当前进程内重试。

## 哪些入口使用

- **飞书 Application 入口**：自动启用持久化投递。scope 是 App ID，只恢复当前应用对应的记录；更换 App ID 不会把旧应用的回复投给新应用。
- **Web**：继续使用已保存聊天历史和客户端游标恢复，不为每个 WebSocket 创建投递记录。
- **SDK / Shell / 显式 on_reply 回调**：由调用方消费回复，不自动创建渠道投递记录。
- **无关联事件的通知**：使用原来的发送路径，不提供持久化补发。当前仅维护 Web、飞书和命令行三个 Channel。

## 顺序、失败和重启

默认最多 8 个发送任务并行。同一 `(channel, scope, chat_id)` 只发送最早的未完成记录，包括来自不同 Cota session 的记录；前一条尚未完成时，后一条不会越过。其他目标可以继续发送。

默认单次渠道调用超时 10 秒，最多尝试 8 次，失败后按 1、2、4 秒等指数退避，延迟上限 300 秒。attempts 在调用渠道前保存，重启不会清零；飞书适配器内部的短暂 HTTP 重试包含在一次渠道调用中。

| status | 意义 |
|---|---|
| pending | 等待发送、发送中，或等待下次重试 |
| delivered | Channel 返回成功；飞书表示平台 API 接受，不代表用户已读 |
| failed | 自动尝试耗尽；记录保留，等待人工检查和重试 |

重启后自动恢复 pending。失败的头部消息会阻挡该目标的后续回复，以保留顺序；检查凭据、权限、网络或平台限制后，可以显式重试。错误只存类型，具体原因查运行日志；渠道不能吞掉错误后返回成功。

如果渠道已成功，但保存 delivered 状态时数据库暂时不可用，当前进程只重试写入结果，不再次发送。若此时进程崩溃，恢复后可能再发送同一事件。这属于至少一次投递；飞书使用稳定 UUID 去重，但不能承诺无限时间范围内绝对不重复。达到重试上限的未确认记录保存为 failed / AttemptsExhausted，人工重试前需考虑前次可能已经送达。

## 查询和重试

以下是受信任的服务端 Application API，不是公开的匿名管理接口：

```python
# 从 submission.wait() 或 app.history() 的 bot 消息获取 event_id。
status = await app.delivery_status(session_id, event_id)
# 无投递记录时返回 None。

retried = await app.retry_delivery(session_id, event_id)
# 仅 failed -> pending；重置本轮重试计数。
# delivered / pending / 不存在返回 False；不会重新提交用户输入。
```

授权由调用方负责。查询输入的 receipt.status=completed 不等于 delivery.status=delivered，二者不要混用。日志会记录重试和最终失败的 event_id。

## 关闭与边界

Application.close() 立即拒绝新提交，取消尚未执行的排队输入，给正在执行的轮次最多 5 秒收尾；超时取消后再按 Runner 现有期限等待退出。已经保存的回复不会丢弃。随后投递器最多等待 5 秒，尝试完成当前可发送的任务，再关闭渠道；尚未完成或处于未来退避时间的记录留到下次启动。

每个 Store 仍只允许一个服务执行进程，不提供分布式领取锁。尚未保存的用户输入队列仍是内存队列。群聊 Bot 回复可使用同一投递机制；不包含跨群广播、历史回复自动回填、数据库记录清理或已读状态。

高级嵌入部署可在 Application 的 channel_limits 中设置 delivery_concurrency、delivery_max_attempts、delivery_retry_delay、delivery_max_retry_delay、delivery_poll_interval、delivery_shutdown_timeout；send_timeout 继续与 ChannelManager 共用。CLI 使用上述默认值。
