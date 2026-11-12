# 会话附件

附件是 user_utter / bot_utter 的可选组成部分，沿用会话、历史、输入去重、出站与 Debug。文件字节独立保存，不增加 Event 类型或把 PDF/base64 塞入对话事件。

```json
{
  "text": "绘本做好了。",
  "attachments": [
    {"id": "f_0123456789abcdef0123456789abcdef", "name": "绘本.pdf", "mime_type": "application/pdf", "size": 128000}
  ]
}
```

没有附件时省略该字段。允许纯附件消息。每条最多8个文件，每个文件1字节至20 MiB；WebSocket 只提交稳定 ID，不承载字节。文件元数据由 Cota 生成，客户端不能伪造。相同 message_id 重试必须保持附件相同。

## Web 接入

先有已授权会话，再上传原始文件字节：

```http
POST /api/conversations/{session_id}/files
Authorization: Bearer <应用提供的凭据>
Content-Type: application/octet-stream
X-File-Name: <encodeURIComponent(file.name)>

<原始文件字节>
```

201 返回四字段引用。文件名头使用 UTF-8 百分号编码。上传不会发送消息、触发 Pi；前端确认发送时通过 HTTP 或 WebSocket 提交：

```json
{"type":"send", "message_id":"input-001", "text":"请看看参考图", "attachments":["f_0123456789abcdef0123456789abcdef"]}
```

HTTP 消息接口使用同一字段但不含 type。发送只有文件时 text 可为空。引用必须属于目标会话；历史和实时消息都返回附件元数据，重连仍使用同一个 ID。

下载：`GET /api/conversations/{session_id}/files/{file_id}`，需 Bearer 凭据并通过当前会话授权。响应使用 Content-Disposition attachment、no-store 和内容类型保护。不提供匿名令牌、不把 Bearer 写进链接。群成员被移除后不能发起新的附件下载。

`CotaClient` 提供：

```javascript
const uploaded = await client.upload(file); // 浏览器 File
await client.chat('请看看', 'input-001', {attachments: [uploaded.id]});
const {blob, name} = await client.download(uploaded);
```

默认聊天应用有文件选择器和下载卡片。下载通过带授权的 fetch，再使用临时 Blob 保存。未发送消息在重连时保留 ID，不再次上传或把字节写入 localStorage。选择但尚未发送的文件不构成会话消息。

## Cmdline 输入

在 `cota shell` 中使用 `/file` 添加附件，再输入说明发送：

```text
/file "/Users/你的名字/参考图.png"
/file "./资料/故事设定.pdf"
请参考这些资料设计绘本主角
```

每条 `/file` 添加一个文件，可以连续添加。直接回车发送纯附件消息；`/clear` 清空待发送附件，`/stop` 退出而不发送剩余附件。终端会显示已添加的文件名和数量。添加失败不会触发模型，也不会丢弃之前添加的文件。

支持绝对路径、`~` 和相对启动 Shell 目录的路径；含空格的路径须加引号或用反斜杠转义，也可在 `/file ` 后拖入文件路径。路径只解析，不执行 Shell 命令或展开环境变量。文件必须存在且是普通文件；空文件、目录、符号链接和超限文件会被拒绝。

这是本地用户显式选择文件，所以允许选择 Bot 工作区外的文件；模型的 `send_files` 工作区限制不受影响。添加时复制到当前会话存储，原文件后续修改不会改变附件。发送时与 Web 一样进入 user_utter、DST、历史和 Debug；无需新增工具或 Event。`/clear` 只取消待发送引用，不删除文件副本，副本沿用部署方的保留策略。

## Cmdline 收到文件

Bot 发送的附件在 Shell 中显示编号、文件名、大小和存储路径。UTF-8 文本及 Markdown 等常见文本文件还会显示简短预览（最多 12 行、1,600 字符），不会把大文件或二进制内容直接输出到终端。普通模式和 Debug 模式使用同一展示。

```text
/files
/open 1
```

`/files` 列出本次 Shell 最近收到的 64 个附件；`/open 编号` 使用系统默认应用查看 PDF、常见图片、文本或办公文档。收到附件时不自动启动应用，文件命令不发送给模型。普通终端不内嵌显示图片或 PDF。

打开前重新校验会话作用域及原始文件完整性，在 `.cota/files/<file_id>/view/<原文件名>` 准备查看副本，让系统正确识别扩展名。原始 `data` 仍是下载与历史的不可变证据；查看副本已被本地编辑时会提示错误，不覆盖修改。可先把编辑稿另存并移走查看副本，再打开原附件。附件不可用时显示明确提示，其他附件和文字仍可显示。

## Bot 交付

personal 的 machine 环境可启用 `send_files`。它以 Pi AgentTool 格式定义，由 Cota 绑定当前会话，不接受模型提供的 user_id/session_id：

```yaml
deploy: personal
tools:
  allow: [http_request, send_files]
```

参数为 `{"paths":["report.pdf"],"text":"报告已附上。"}`。路径相对 environment.workspace，也可使用其内部的绝对路径；拒绝越界、目录和符号链接。先复制文件，再持久化带附件的 bot_utter，随后进入正常投递。成功只表示已提交，不表示用户已经下载。

`FileStorage.capabilities()` 返回实际 `max_file_bytes` 和 `max_attachments`，由 Runtime 传入 Pi 的 `send_files` 工具说明及数量约束。Bot 配套程序应在最终审校前按该上限检查导出文件，不能假定“PDF已生成”就能发送。默认仍为20 MiB与8个文件。

整批路径先预检，任意文件无效时不部分交付。失败返回简洁的结构化信息，例如 `reason: file_too_large`、`file`、`actual_bytes`、`max_file_bytes`、`retryable: false` 与下一步建议；具体 reason 以实际返回为准。超限应调整导出或报告限制，不能原样重复调用。附件错误属于工具结果，不新增 Event。

service 环境不开放部署机器文件。受信任 SDK/工具可将自己生成的文件写入 FileStorage，并将引用放进 bot_utter；不能让模型随意选择宿主机路径。

Web 支持附件；shell 输出副本位置。Channel 插件声明 `supports_attachments = True` 后负责平台文件上传及发送，通过绑定的 `channel.files.resolve(message.session_id, ref['id'])` 读取会话副本。未声明支持的 Channel 明确失败，可靠投递不会反复重试这种错误。飞书第一版仍只有文本，没有文件收发适配。

## 持久化与 SDK

默认后端为 Bot 的 `.cota/files/`，保存副本和包含 session_id、哈希的 sidecar 元数据。已发送版本不随原文件修改而变化。迁移时须同时保留 Store 与该目录；多人服务需使用持久卷，MySQL 不会自动备份这些本地字节。第一版没有自动清理未发送上传文件，由部署方按保留策略管理。

无 Bot 配置目录的 SDK 可显式注入后端：

```python
from cota.agent import Agent
from cota.files import FileStorage

agent = Agent(file_storage=FileStorage('/persistent/cota-files'))
file = agent.files.put('session-001', 'alice', '说明.txt', b'hello')
# Application.submit(..., attachments=[file])；调用方先完成身份与会话授权。
```

FileStorage 不实现账号、成员管理或外围认证，只强制校验传入的会话作用域。文件 ID 不是访问凭证。纯文本 SDK 无需文件后端。

## 文件展示与模型理解

在 endpoints.yml 的 `llms.<对话模型>.vision: true` 显式开启后，不超过2 MiB的 PNG/JPEG/WebP/GIF 可在模型请求边界转为真实图像输入。默认 false，保留纯文本主模型协调专门视觉服务的能力；自定义模型适配器可声明 `supports_images = True`。字节不会因此写入 user_utter、DST 或快照；Debug 请求记录仍可能含实际图像。

附件图片与工具返回图片使用相同的请求选择：启动和恢复只传工作消息与不可变资源引用，不传全部历史像素。Pi 在模型请求前按预算加载最新用户图片和当前待观察的工具图片批次，较早图片保留来源、精确版本和重新读取说明，已有文字观察继续保留。该机制同时适用于原生 Pi provider 和自定义模型适配器。历史附件注册引用无需读取文件；真正加载时由 Cota 校验会话归属和完整性。一个 run 内 Node 有界缓存已加载的资源，同一 ID 不允许替换内容。

模型可通过 Pi `read` 读取 `/bot/.cota/context-images/...` 只读虚拟路径，复查旧版本；它不是可交给 bash 的磁盘路径。personal 的附件说明另保留真实 `local_copy`，供脚本或专门视觉服务使用。较大图片会明确提示超出自动视觉输入限制。PDF、Office、音频等只提供引用，不自动解析或声称模型已理解。personal 可使用已授权文件工具读取会话副本，按 Skill 连接解析、缩放或专门视觉服务。发送成功不能代替内容审校。

标注导出用“[附件：文件名]”保留消息位置，沿用原 Policy 格式；它是可编辑说明，不是二进制回放格式。
