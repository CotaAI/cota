# 应用接入契约

Application 是外围应用接入 Cota 的统一入口。一个服务进程创建一个长期存活的 Application；消息统一接收并持久化，需要 Bot 回应时才经过 ChannelRunner、Processor 和 Pi。不要为每条消息创建新的 Agent 或 Runner。

```python
import asyncio
from cota import Agent, Application

async def main():
    agent = Agent.load_from_path('./bots/weather')
    async with Application(agent) as app:
        submission = await app.submit(
            user_id='myapp:tenant1:user1',
            session_id='myapp:tenant1:conversation1',
            text='你好',
            message_id='input-001',  # 可省略；重试时应复用原 ID
        )
        result = await submission.wait()
        print(result['receipt'])
        for message in result['messages']:
            print(message['role'], message['text'])
        history = await app.history('myapp:tenant1:conversation1')
        print(history)

asyncio.run(main())
```

源码中的可运行示例：`python scripts/application_example.py --config ./bots/weather --text "你好"`。先填写该 Bot 的 endpoints.yml；重复测试时可传 --message-id 检查输入去重。

## 责任与 ID

调用 Application 前，外围应用完成登录验证和会话访问授权。Application 是受信任的服务端接口，不能直接接受浏览器自行声明的身份。

| 字段 | 来源与用途 |
|---|---|
| user_id | 外围验证的稳定用户身份；隔离用户记忆 |
| session_id | 外围验证的对话标识；隔离 DST、历史，决定执行顺序 |
| message_id | 外围输入 ID，省略时自动生成；同一会话内去重 |
| event_id / sequence | Cota 的执行事实 ID / 序号；聊天历史只投影 user_utter、bot_utter |

同一个用户可以有多个 session；多个用户也可以参与同一个 session。后者是否允许由外围授权决定。不同租户的 ID 应包含租户范围；不同 Bot 服务应使用各自的 Store 或存储命名空间。这里只隔离对话与记忆，不是工具文件系统的沙箱隔离。

## API

- `await app.start()` / `await app.close()`：管理 Runner、Channel 和 Agent 资源；也可使用异步上下文管理器。关闭后不能重启同一实例。
- `await app.submit(user_id=..., session_id=..., text=..., message_id=None)`：先保存 user_utter，再返回 Submission；不等待模型完成。
- `submission.message_id`：实际输入 ID；`duplicate` 表示已存在同 ID 的接收记录。
- `await submission.wait()`：返回 `receipt` 和本次输入及其运行产生的聊天消息；不会混入后续轮次。取消等待不取消执行。
- `await app.receipt(session_id, message_id)`：查询当前/已有输入状态，不存在则返回 None。
- `await app.history(session_id, after=0, limit=100, until=None)`：返回 `messages, cursor, through, has_more`。分页继续传 cursor；固定一次历史范围可传首次返回的 through 为 until。

session_id、user_id、message_id 最长 255 字符，正文 1–32768 字符。历史 limit 为 1–500，分页按原始事件序号推进，某页可能没有聊天消息，仍应按 has_more/cursor 继续。

输入不合法抛 ValueError，未启动/已关闭抛 RuntimeError；队列满抛 asyncio.QueueFull，同 ID 内容冲突抛 InputConflict（来自 cota.inputs）。运行失败在 wait 的 receipt 中返回 failed/interrupted 和简要错误码，内部错误由日志与 Debug 查看。

## 执行与恢复边界

同会话的明确请求按 FIFO 执行，跨会话有限并发；群聊主动参与任务优先级较低，排队时可被新消息作废，但不会抢占已经开始的执行。Web 与飞书都经过同一个 Application 执行处理器。Channel 负责协议、身份映射和投递，不再自行组织模型上下文。

Store 使用现有事件派生输入记录，不新增账号、成员、输入状态表。Application 在返回 Submission 前保存 user_utter，queued/running 的实时排队位置仍由进程内 Runner 管理。启动时有界恢复已接收且尚无 run_started 的 direct 输入；同一会话新输入排在旧输入之后。断线不取消执行，同一 message_id 不重复启动；已经开始但中断的运行不会自动重放可能有副作用的操作。

wait 中的 completed 代表模型执行完成，不代表外部平台已经收到回复。投递失败不会重跑模型。飞书回复与投递记录在同一次 Store 事务中保存，发送失败及重启可恢复；查询和人工重试见 [回复投递与恢复](delivery.md)。当前为单执行进程协调，不提供跨进程会话锁或分布式任务队列。输入持久化与开始运行后的副作用恢复是两件事。

Web 的登录、会话授权、重连协议见 [Web 接入](api.md)；平台身份映射见 [飞书单聊](feishu.md)。

## 群聊输入

`app.submit` 另外接受 `mentioned=False`、`sender_name=None`、`reply_to=None`。群聊普通消息返回 recorded，未启动 Pi；@ 和主动参与的具体语义、输入并发、重试边界见 [公共群聊基础](group.md)。群聊不要通过低层 Processor 入口提交。

## 消息分页与列表摘要

`app.message_page(session_id, before=None, limit=50)` 返回最近一页聊天消息；使用返回的 cursor 作为下一次 before，向前翻页。消息按 sequence 升序排列并带 timestamp。`app.history` 仍用于 after/until 范围的增量同步。

`app.conversation_summary(session_id, after=0, exclude_sender=None)` 查询最后一条消息、最近活动时间及游标后的未读消息数；exclude_sender 可排除用户自己的发言。它只查询 Store，不维护成员或阅读状态。可选聊天应用在自身数据库保存阅读游标；外围应用可以自行保存。

接收消息与模型执行相互独立：执行期间后续输入可继续落库，Processor 使用本轮触发输入对应的上下文视图执行，最后将事实合入 Store。后到的输入不会进入前一轮模型上下文。
