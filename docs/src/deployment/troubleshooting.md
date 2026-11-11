# 故障排除

先区分：配置加载失败、输入接入失败、Pi/工具执行失败、回复投递失败，以及只是模型业务判断不符合预期。它们的记录和处理位置不同。

## 安装与启动

| 现象 | 检查与处理 |
| --- | --- |
| 找不到 cota | 确认虚拟环境及安装位置；使用 `python -m cota --help` 验证当前 Python |
| 源码运行找不到 Node/Pi | 检查 Node >=22.19，执行 `npm ci --prefix cota/runtime/pi`；editable 不带发布 runtime |
| 普通 wheel 构建失败 | 发布 wheel 需准备 bundled runtime；源码开发用 `uv pip install -e .`，见 [安装](../installation/install.md) |
| endpoints 中模型字段为空 | 直接填写 key/apibase/model；不是填写 COTA_API_KEY 环境变量 |
| Unsupported agent/config keys | 按 [配置参考](../configuration/overview.md) 使用当前字段；旧 Action/Runtime 配置不兼容 |
| Policy artifact missing/stale/invalid | 核对 policy/*.yml 与 options，执行 train，再 `train --check`，重新加载 Agent |
| Skill 名称未知 | 检查 SKILL.md frontmatter 和 Pi 目录；Policy 引用名称必须一致 |
| Incompatible Store schema | 事件表 schema 不兼容；先备份。有价值的数据需要单独迁移，勿直接删库 |

Snapshot 缓存不兼容可以回退重放；它不等同于旧事件表缺少列。修改系统时间、快照或模型消息 JSON 来跳过校验会掩盖问题。

## 已启动但聊天不工作

- `cota run` 默认只提供通道 API；要页面加 `--chat-app` 并访问 `/chat/`，不是旧 front.md 页面。
- `/api/health` 返回 503：查看通道就绪和启动日志；200 也不代表模型凭据或工具服务正常。
- 403：检查 token、会话权限和 Origin；前端不能在 send 消息里自行声明 user_id/session_id。
- 409/input_conflict：同一 message_id 只能代表同一次输入，不能换内容后复用。
- 429/busy：保留原 message_id 稍后重试，避免生成第二条相同业务请求。
- group 普通消息只有 recorded：这是预期行为；passive 只在明确 @ 时运行，引用 Bot 不自动触发。
- proactive 没有回复：检查最近发言冷却、判断是否过期，以及 Debug 中 participation 请求；判断 NO/错误时保持安静。

WebSocket 使用 resume 绑定身份和会话；重连传最后游标，客户端按 event_id 去重。聊天历史 sequence 跳号正常，因为它投影自包含工具等事实的完整事件流。

## Skill、工具与 Policy

- 有 Skill 目录但没有读取：目录只提供候选，读取由模型选择；查看实际 request 和 tool_started。
- read 成功不代表业务成功：检查是否执行真实查询，以及 tool_result 的内容。
- 文档提到的工具不存在：先注册 Tool/MCP，检查 allow/deny；修改 Skill 不会安装依赖。
- 出现 requested_arguments：Pi 对模型参数做过类型转换；arguments 是实际实参，requested_arguments 保留不同的原始提议。
- Policy 没按预期工作：先确认实际 request 的 business_guidance，再看输入事实、result 条件和选择诊断；不能仅凭案例被选中断定模型会遵循。
- 训练/标注成功但在线没变化：已有 Agent 不热更新，重新加载；训练型策略还需新产物匹配当前配置。

## 执行与投递

执行失败时用 session_id、run_id、request_id、tool_call_id 关联事件与日志。
Debug 下可查看失败的模型请求；普通模式不会保存完整请求体。网络/供应商错误由日志诊断，不单独制造 model_error 事件。

如果上次进程中断，旧运行可能仍是 running；先确认旧执行器已经停止并取得会话独占权，再按 [DST 恢复规则](../concepts/dst.md) 处理。不要自动重放未知结果的工具。

Bot 已生成回复但用户没看到：

- Web：检查历史是否保存、resume 游标、授权及慢连接断开；从历史补取。
- 飞书：检查 deliveries 状态、应用范围和平台权限；人工重试投递，不重新执行模型。
- completed 不是送达证明，平台 API 接受不是已读证明。

## 收集可复现的信息

```bash
cota --version
cota shell --config ./my-bot --debug
```

保留相关会话/运行 ID、事件序列、实际工具结果、必要的请求诊断，以及去掉密钥的配置。
开发者可以运行 `python scripts/check.py --coverage` 检查框架合同，但固定模型测试不评价真实业务准确率。
不要把整个 workspace、真实用户对话或完整 Debug prompt 无筛选地当作公开问题附件。
