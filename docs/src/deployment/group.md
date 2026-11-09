# 公共群聊基础

同一个 Bot 部署使用一种会话模式。配置在 agent.yml，不让每条客户端消息改变模式：

```yaml
dialogue:
  mode: group
  response: passive
  prompt: |
    你是旅行讨论群中的助手。
    区分成员的需求，回答简洁，不把某个人的偏好当作全群偏好。
```

mode 默认为 direct，response 默认为 passive。direct 下每条输入正常触发回复，用户消息保持普通文本。group 下用户消息携带发言者身份、可选显示名、@ 和引用信息；Bot 的 assistant 消息与工具协议保持原样。修改已有会话的模式会报错，请使用新 session，或为另一场景部署独立 Bot/Store。

## 何时回应

- passive：只有明确 @ 当前 Bot 才启动 Pi。引用 Bot 消息本身不触发回复。
- proactive：@ 仍然直接触发；普通消息可进入独立的、无工具的参与判断。只接受模型明确返回 YES，其他结果、异常和超时都保持安静。

主动判断使用 dialogue.llm 和 Bot 的角色 prompt，不新增配置项。当前默认规则：

- 连续消息等待 1 秒安静窗口；新消息延后判断，但同批最多合并 3 秒。
- 同群两次判断至少间隔 2 秒。NO、异常和超时只受到短时判断节流，不会封锁随后一分钟的新需求。
- 距离最近一条实际 bot_utter 不满 60 秒时，普通消息不触发主动参与；包括刚刚响应 @ 的回复。根据 Store 中的发言时间判断，因此重启后仍有效。仅有 run_started 或没有发言的执行不产生这个冷却。
- 明确 @ 绕过上述判断与冷却，优先于尚未执行的主动任务；已开始的模型和工具执行不被强制打断。

ParticipationJudge 仅判断当前是否值得介入，不负责选择 Skill 或执行任务。它读取最近最多 24 条用户和 Bot 发言，组织成最多 16000 字符的有效 JSON，保留发言者、@、引用关系，并提示上下文可能截断。能力摘要使用 Pi 发现的 Skill 名称和描述，以及当前允许的工具名称和描述；不注入 SOP，也不向判断请求开放工具。能力 JSON 最多 12000 字符，省略项带计数。Skill 摘要在 Application 生命周期内缓存，修改目录后重启服务刷新；实际 Pi 执行仍执行自己的资源发现与权限检查。

模型被指导对闲聊、感谢、已回答、已撤回、无需 Bot 的成员间交流和不确定情况保持安静。参与判断不构成执行外部写操作的授权。判断总超时 10 秒，只接受完整的 YES；NO、非法输出、工具调用、异常和超时均保持安静。具体业务仍由 Pi 结合 Skill 和 Policy 决策。

判断在独立的有界后台任务中运行，不占用 Bot 执行位置。每群只保留最新候选，待考虑群数量不超过 max_pending，判断并发不超过 concurrency；容量不足时保存消息并跳过本次主动参与。明确请求可挤出尚未执行的主动任务，不会挤掉正在运行的工具。

新消息会使旧判断失效，等待合并后评估最新内容。YES 返回后、排队获得执行位置时都会复核；第一次执行检查点还会在 Store 会话锁内核对批准时的事件序号。期间出现新消息或其他回复，就不写入过期的 run_started，也不执行工具。成功提交 run_started 后，本轮上下文保持固定，新消息留给后续判断；不会为了撤销已经开始的副作用而重跑或强行中断工具。

主动判断会消耗模型请求。Debug 下保留 purpose=participation 的独立请求记录，run_id 为空；判断、等待、冷却和失效均不新增 Event。仅在实际执行时产生 reason=proactive 的 run_started。短时判断节流与候选队列属于进程内状态，重启不重新执行历史候选，也不会对重复投递重新判断。

可以用 [可选聊天应用](chat-app.md) 验证闲聊、连续补充、他人已回答、问题撤回、明确 @ 等场景。自动测试覆盖调度、提示词内容、权限和恢复边界；实际参与准确率仍需要真实群聊样本验证，不能由模拟模型测试推定。

授权接收的普通消息同样保存为 user_utter，无需额外“忽略”事件。它们的 receipt.status 为 recorded，表示消息已经保存；不等于发生过 Bot 执行。只有执行真正开始，才产生 run_started，包含触发消息、响应原因和上下文截止位置。

## 服务端 SDK

调用前由外围完成身份与成员权限验证。多个成员使用同一个 session_id，各自保留独立 user_id：

```python
async with Application(agent) as app:
    await (await app.submit(
        user_id='tenant:alice', session_id='tenant:travel-group',
        text='周末去杭州。', message_id='m1', sender_name='小王',
    )).wait()  # recorded，不调用 Pi

    result = await (await app.submit(
        user_id='tenant:bob', session_id='tenant:travel-group',
        text='帮我们查一下天气。', message_id='m2',
        mentioned=True, sender_name='小李', reply_to='m1',
    )).wait()
```

mentioned 必须是 boolean，表示用户确实指定了当前 Bot；不根据正文中的 @ 字符推断。sender_name 和 reply_to 可省略。message_id 重试时保持不变；同 ID 改变正文、发言者、@ 或引用会被视为冲突。

Application 是群聊唯一协调入口。不要直接调用 Processor.handle_message/handle_inbound_message 或绕过它启动群聊 Runtime；这些低层旧入口会拒绝 group。命令行仅支持 direct。

## Web

群聊使用 ExternalAccess 或外围提供的等价授权适配器。没有现成前端时，使用 `cota run --chat-app` 启用 [可选聊天应用](chat-app.md)，由它提供会话和成员授权。核心 GuestAccess 是单用户会话，不支持群成员管理，group 服务直接使用它会在启动时报错。

身份仍在 WebSocket resume 时绑定。群消息帧示例：

```json
{"type":"send","message_id":"m2","text":"查一下天气","mentioned":true,"reply_to":"m1"}
```

普通消息省略 mentioned 或传 false。客户端不能传 sender_id、user_id、session_id、sender_name 或 conversation_type 来覆盖身份和场景。已授权用户设置 mentioned=true 表示向当前 Bot 发起 @ 请求。

浏览器客户端也支持：

```javascript
await client.chat('查一下天气', 'm2', {mentioned: true, reply_to: 'm1'});
```

这些字段会随重试/重连保留。群用户消息的公开历史额外带 sender_id，以及实际提供的 sender_name、mentioned、reply_to；直接聊天的消息投影保持不变。建群、成员管理、群列表和页面属于外围应用；可选聊天应用提供其最小实现。Web 在每个排队或实时帧投递前重新验证身份和成员权限，失效连接在下一次发送或投递时关闭。

## 飞书

在相同 agent.yml 中配置 mode: group，启用飞书 Channel 即可选择群文本接入。Application 将模式传给适配器，不需要 channels.feishu 再配置一套模式。

启动时使用官方 Bot 信息接口取得当前 Bot 的 open_id，按事件 mentions[].id.open_id 判断是否 @ 当前 Bot。@ 别人、名字相似、正文中写 @ 均不算。群会话按 app_id、tenant_key、chat_id 隔离，多个群成员共享该群上下文。direct 服务只接收单聊，group 服务只接收群聊；机器人来源消息仍被忽略，避免相互循环。

必须在飞书配置群消息接收权限及事件订阅，且允许 Bot 加入目标群。实际收到的上下文取决于平台向应用开放哪些消息；只开放 @ 消息时，Cota 无法看到未投递的普通讨论。allow_from 继续限制可接收的发言者。回复使用现有持久化投递，目标是群 chat_id；补发不重新运行模型。

## 并发、恢复和隐私

消息接收与模型执行分开：Store 追加群消息使用短会话锁；Pi 使用独立的执行视图，新生成事件通过 ID 合并到最新日志，不能覆盖期间收到的消息。普通消息无需等待正在运行的模型或工具。Bot 执行仍按会话串行，不同会话有限并发。平台消息总线还有一个有界的 @ 重试队列，容量为 max_pending；它满载后会对接收施加背压，避免无限堆积。关闭时取消进程内排队和重试，已保存但未启动的消息仍为 recorded，重启不自动执行。

通常本次上下文截至触发消息，后来到达的消息不会进入本轮工具循环。若执行队列已满，@ 消息可能已保存但尚未安排执行，调用方收到 QueueFull 后可重试同一 ID。若重试发生在较新的执行完成之后，会固定一份当时的历史上下文，同时仍明确回答原来的触发消息。已有 run 的输入不会因重试再次执行。

原始 Events 按实际保存顺序排列。模型上下文会将执行过程中收到的消息留到该执行之后，确保 assistant/toolResult 协议连续；它是事件投影，不改变原始日志顺序。压缩保留成员归属，历史原文仍在 Store。Snapshot 缓存版本升级后自动从 Events 重建，无需删除数据库。

群聊不会自动加载任一成员的个人跨会话记忆。第一版使用群内历史和摘要；不新增一套群长期记忆接口。工具文件系统和外部服务权限仍由部署配置负责。

无 run 的群消息在重启后仍为 recorded；未结束且没有活动执行器的 run 为 interrupted，不能当作普通背景消息。执行前的失败/排队取消通过当前 Submission.wait 或 Web receipt 返回安全错误，不能将这类即时错误误认为持久化 run 事实。没有分布式执行锁，也不自动恢复可能已经产生副作用的工具执行。
