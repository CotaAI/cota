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
| debug.provider_response | Pi 原生调用为组装完成的 Pi 消息；Python 适配器为供应商响应，若提供 |
| debug.preparation | Policy 的选择、thought、预算省略和准备诊断 |
| debug.request_size | 按 system/user/assistant/tool 分类的实际字符数、system 内 Policy/Skill 目录大小、工具定义字符数、图片数量和内联字节数 |
| debug.transport | OpenAI 适配器的总时限、最大重试次数和各 HTTP 尝试：number、started_ms、headers_ms、status_code、status；完整响应返回时记录 response_ready_ms；Pi 原生流另记录首个公开文字的 first_text_ms |
| debug.preparation.context_budget | Pi token 估算、实际 usage 推导预算、模型容量及来源、预留 token；serialized_bytes / max_request_bytes 展示序列化预算，images / max_images 和 image_bytes / max_image_bytes 展示图片预算；估算不等同供应商计费 |
| debug.usage | 供应商报告的输入、缓存命中、输出和推理 token 数；未提供时不伪造 |

Model Requests 列表显示运行中请求的等待时长，详情显示本次耗时、实际用量和上下文构成，选中该页时自动刷新。等待模型期间没有新的执行事件是正常情况，不额外添加心跳 Event。查看较早的请求时仍可手动刷新或返回列表。

`transport` 时间均从该次 Cota 模型调用开始计时。响应头可能先于空行保活到达，`headers_ms` 不是首 token 延迟；`response_ready_ms` 是适配器收到完整模型响应的时间。Pi 原生流式请求的 `first_text_ms` 是首个公开文字增量的时间，并不包含此前可能已产生的推理 token；Python 非流式请求不伪造该指标。这些时间不能单独区分供应商排队与上传/网络耗时。模型请求诊断日志记录标识、尝试和状态，不通过异常堆栈复制供应商错误响应体；需要详情时查看 Debug 记录。外围应用自行记录异常时也应遵循自己的敏感信息处理规则。

模型最终回复与同批次工具调用沿 llm_event_id 找到来源请求。没有诊断就不显示 debug。
这是**只读聚合**：底层诊断独立保存于 SQL `model_debug` / `model_debug_bodies` 表或 MemoryStore 映射，没有把大请求复制进每条 Event，也不参与 DST 恢复。

## 普通模式和 Debug 模式

| 内容 | 普通模式 | Debug |
| --- | --- | --- |
| 用户/Bot 发言、工具调用与结果 | 保存 | 保存 |
| 运行边界、压缩、Skill 阅读资源标记 | 保存 | 保存 |
| 模型输出来源、实际 Policy 案例指纹、供应商提供的 token 计数 | 在 Bot/工具来源事件中保存 | 同左 |
| 完整请求、供应商响应、Policy 详细选择诊断 | 不保证保存 | 独立诊断保存 |
| 已提交事件完整 JSON 日志 | 不开启该详细文件输出 | workspace/debug/execution.log |

不同调用由 purpose 区分：dialogue、policy、knowledge、compaction、policy_embedding、participation 等。
没有独立 model_response/model_error/skill_read Event；主要结果在 bot_utter/tool_started/tool_result 中，失败请求在诊断和日志中。
`tool_result.payload.resource` 标记 Skill 阅读；`run_metadata` 保存发现的目录，而不是 skills_loaded Event。

核心事件保存失败必须停止继续执行；日志或可选诊断写入失败只记录警告，不改变业务结果。
关闭 debug 后不能追溯还原从未采集的完整 prompt，也不能从供应商接口取得模型未公开的隐藏思维链。
请求中可能包含用户内容和业务资料；该页面是开发调试入口，不是可分享给终端用户的 Bot 链接。

状态及事件契约见 [DST](../concepts/dst.md)，排查步骤见 [故障排除](troubleshooting.md)。

Web 与 Shell 的流式片段是临时展示，不会在 Events 中逐条出现。完整公开文字仍保存为 bot_utter；同一响应包含工具调用时，公开发言关联首个 tool_started，模型上下文只投影一次。包含 Pi 续接签名的响应可在来源事件中保留 llm.continuation，用于恢复协议，不会出现在公共聊天历史里。

页面侧栏同时显示当前执行阶段及等待时长：准备下一请求、等待主模型、Pi 上下文压缩、等待具体工具，以及完成、达到限制、失败或中断。它通过少量事件头和请求头推导，不恢复完整 DST，不读取大请求正文，不产生心跳 Event。这里显示的是最后观察到的执行阶段，不能代替执行者存活检测或跨进程所有权判断。

`max_iterations` 限制的是 Pi 的模型决策轮数，不是 Event 数量；同一响应的多个工具调用会产生多条事实。达到限制保留 `limited` 状态，并提示在本会话继续。运行总超时及原生模型请求超时保留失败状态与已提交事实，给用户明确的超时提示；不会自动重放可能已经产生外部副作用的工具。具体模型请求的时限和原因见对应请求诊断。

SQL 中请求正文、准备详情及响应正文独立保存，状态更新只修改小记录。页面和 SDK 读取到的 JSON 结构不变。这样在多图长任务中查看等待状态，不会反复重写整个 prompt。
