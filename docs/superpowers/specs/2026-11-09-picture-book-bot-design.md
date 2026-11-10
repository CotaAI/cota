# 绘本 Bot

2026-11-10 更新：本文记录最初实现设计。交付已迁移到 Cota 的统一附件链路，专属 serve.py、匿名令牌发布及下载已删除；当前行为见 [会话附件](../../src/concepts/attachments.md)。

用户已确认：第一版支持 shell 本地成书、Web 下载交付；绘图与看图使用可配置的 OpenAI 兼容接口，由用户随后填写服务配置。

## 边界

- `bots/picture-book` 是可分享的 personal Bot，不是多人隔离沙箱。复用 Pi 的 Skill、文件与 Bash 工具，不增加核心绘本 Tool 或执行循环。
- 完整携带用户提供的 `creating-childrens-picture-books` Skill，保留参考资料、模板、验证器和来源说明；运行不依赖作者的绝对路径。
- 主模型沿用 `llms.default`。Bot 自己的 `picture_book.image` 和 `picture_book.vision` 配置由附带脚本读取，不假装 Cota 的文本 LLM 工厂支持图片生成。
- Images generations/edits 与 Chat Completions vision 是两个实际协议。参考图必须作为文件上传；视觉检查必须发送真实图像。只接收内联 base64 图片响应，供应商仅返回 URL 时明确失败，避免凭证和任意下载地址泄露。
- 不调用真实付费模型来完成仓库验收；受控 HTTP 响应验证协议，真实模型质量由用户配置后验证。

## 执行与恢复

Pi 按 Skill 创作简报、故事、分镜和主题约定，写入项目目录；附带脚本处理环境检查、单张绘图/编辑、视觉检查、PDF 排版/全部页面渲染、发布。中文由排版层生成，页面使用显式图文位置。主模型决定调用顺序，脚本不是另一个 Agent。

每次生成保存提示词、引用资产哈希、模型名及请求结果记录，不保存凭证或 base64。成功输出可按相同输入复用；已有不同输入不得静默覆盖。网络失败及中断不自动重试付费生成。资产按项目保存，跨会话继续时先检查文件；不声称拥有 exactly-once 外部模型调用。

排版不自动设置人工/模型审校通过。PDF 的空白页、页序、纸张映射遵循原 Skill；渲染所有页并产生预览。验证器检查最终包，视觉/语言质量仍需要真实审校证据，实物打印保持待验证。

## Web 交付

Bot 附带 `serve.py` 组合公开的 `cota.webapp.create_app`，保留其启动、关闭、Store 和 Debug；只附加 `/books/<token>/<file>` 下载路由。发布脚本复制明确选定的 PDF、预览与打印说明到 `.cota/downloads`，不托管整个工作目录。链接为有期限的随机能力令牌，持有者可下载；默认监听回环地址，撤销时删除发布目录。这个选择不等于会话成员认证，也不适合未经隔离的公共 personal 服务。

聊天页面只补充安全链接渲染：不执行 HTML，不支持 javascript/data/file URL。消息仍为普通 bot_utter，下载链接通过同一 Store 历史和 WebSocket 重放，无新 Event、表或附件执行器。

## 验证

覆盖完整模板复制、缺配置提示、真实参考图上传、视觉图片输入、错误不泄露密钥、重复生成保护、PDF 页数/尺寸/嵌入字体/留白/溢出、完整渲染、限时发布、越界与符号链接拒绝、真实 HTTP 下载与撤销、WebSocket/Store 历史、Pi 多步工具与恢复。Policy 与 reply-review 验证文件使用现有格式。
