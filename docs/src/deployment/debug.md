# Debug 与执行记录

**执行事实始终保存，debug 只增加详细诊断。** 正常运行也必须能恢复会话、追踪调用和查询历史。

## 打开本地页面

```bash
cota shell --config ./my-bot --debug
```

终端输出随机端口、带访问 token 的本地只读页面地址，以及 `workspace/debug/execution.log` 路径。
页面只观察当前 shell 会话，不调用模型或工具，也不提供修改 DST 的入口。退出 shell 后页面关闭。
服务模式也可以打开页面：

```bash
cota run --config ./my-bot --debug
```

此时启动独立的本地 Debug listener，终端打印地址；它不会挂载到公开聊天或 Webhook API。页面可分页浏览 Store 中的会话，选择 Web、飞书或插件 Channel 的会话后查看记录。新会话到来后点击“刷新会话”。每页最多 100 个会话，只查询元数据，不批量恢复 DST。

服务模式的 DST 以 Store 恢复状态和快照为准；没有 Shell 提供的实时 tracker 时，live 显示不可用。停止服务后 Debug 页面一同关闭。此入口只读，不提供重新执行或人工重发操作。
Debug 页面启动失败时记录警告，Bot 服务继续运行；已开启的诊断与日志采集不依赖页面是否可用。

## 调试入口

| Tab | 看什么 |
| --- | --- |
| Events | Store 中已保存的真实事件序列；详情展示完整 JSON |
| Skills & Tools | 本轮初始 Skill 与工具清单、来源、可用状态、缺失原因和执行环境，可切换历史运行；目录不是 Skill 已执行的证明 |
| Model Requests | 最近请求的状态、purpose、完整 request/response，包括没有产生 Bot/工具事件的失败请求 |
| DST | Store 恢复的状态、当前内存状态、物理快照；按需读取，不写回 |
| Deliveries | 当前会话对应回复的投递状态、尝试次数、错误类型与下次重试时间；按事件位置分页，不触发重试 |

Events 的序号属于完整事实流。聊天历史只展示 user_utter/bot_utter，因而可跳号。
快照是某个事件位置的恢复缓存，不是把另一个窗口的“最新 DST”强制同步到数据库。
运行中 live 比 stored 更新是可能的，应结合 revision、last_sequence 和当前提交边界判断。
`discovery.tools` 只在 Debug 中保存，复用已有运行元数据，不增加 Event。该清单表示每轮开始时的状态；权限随后发生变化时，以 Model Requests 中具体请求的 tools 为准。普通模式仍保留原生工具环境元数据并在日志输出初始可用性。

## 查看模型真正收到的内容

在 Model Requests 中打开一次调用，查看 `request`：内置模型适配器记录实际提交给 SDK/HTTP 的参数，包括 messages、tools 和模型设置。
第三方适配器没有接入 provider_request 时，只能保留其适配器输入，不能据此宣称是精确供应商请求。

事件详情会按来源找到诊断，在返回 JSON 的顶层加入 `debug`：

| 字段 | 含义 |
| --- | --- |
| debug.request | 最终请求 prompt、工具声明及参数 |
| debug.response | Cota 适配后的模型响应 |
| debug.provider_response | 供应商原始响应，若适配器提供 |
| debug.preparation | Policy 的选择、thought、预算省略和准备诊断 |

模型最终回复与同批次工具调用沿 llm_event_id 找到来源请求。没有诊断就不显示 debug。
这是**只读聚合**：底层诊断独立保存于 SQL `model_debug` 表或 MemoryStore 映射，没有把大请求复制进每条 Event，也不参与 DST 恢复。

## 普通模式和 Debug 模式

| 内容 | 普通模式 | Debug |
| --- | --- | --- |
| 用户/Bot 发言、工具调用与结果 | 保存 | 保存 |
| 运行边界、压缩、Skill 阅读资源标记 | 保存 | 保存 |
| 模型输出来源、实际 Policy 案例指纹 | 在 Bot/工具来源事件中保存 | 同左 |
| 完整请求、供应商响应、Policy 详细选择诊断 | 不保证保存 | 独立诊断保存 |
| 已提交事件完整 JSON 日志 | 不开启该详细文件输出 | workspace/debug/execution.log |

不同调用由 purpose 区分：dialogue、policy、knowledge、compaction、policy_embedding、participation 等。
没有独立 model_response/model_error/skill_read Event；主要结果在 bot_utter/tool_started/tool_result 中，失败请求在诊断和日志中。
`tool_result.payload.resource` 标记 Skill 阅读；`run_metadata` 保存发现的目录，而不是 skills_loaded Event。

核心事件保存失败必须停止继续执行；日志或可选诊断写入失败只记录警告，不改变业务结果。
关闭 debug 后不能追溯还原从未采集的完整 prompt，也不能从供应商接口取得模型未公开的隐藏思维链。
请求中可能包含用户内容和业务资料；该页面是开发调试入口，不是可分享给终端用户的 Bot 链接。

状态及事件契约见 [DST](../concepts/dst.md)，排查步骤见 [故障排除](troubleshooting.md)。
