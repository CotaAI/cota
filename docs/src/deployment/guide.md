# 部署指南

部署者负责运行环境、模型与工具凭据、数据存储和访问入口。Cota 提供执行与接入组件；它不是自动托管所有 Bot 的云服务。

## 选择入口

| 需求 | 启动或接入方式 |
| --- | --- |
| 自己在终端使用 | `cota shell --config BOT` |
| 独立浏览器聊天服务 | `cota run --config BOT --chat-app` |
| 已有网页、小程序或 IM 后端 | Web Channel 的 HTTP/WebSocket，提供自己的身份授权适配器 |
| 已有 Python 后端 | 长期复用 `Application(agent)` |
| 飞书 | 配置 channels.feishu，使用 `cota run`；可不开放 Web 聊天 |
| 公司 IM 或其它 Webhook/REST 平台 | 安装自定义 Channel 包，在 endpoints.yml 启用，使用 `cota run` 统一管理 |

内置入口为 cmdline、web、feishu；其它平台通过 [自定义 Channel](../development/channel-plugins.md) 接入。插件与内置入口使用相同的生命周期、执行调度和出站路由；需要可靠回复的适配器声明持久化投递能力后，复用 Cota 的投递重试。Web 为 HTTP + WebSocket，同一监听端口；不支持 SSE 或 Socket.IO。

## 接入自定义 Channel

在运行 Cota 的 Python 环境安装适配包，将平台凭据和启用配置放入 Bot 的 `endpoints.yml`，再运行 `cota run --config ./my-bot`。Cota 自动发现适配包声明的 `cota.channels` entry point，创建配置中启用的实例；安装包不会自动连接平台。

Webhook 适配器的路由统一挂在 `/channels/{实例名}`，与 Cota 服务共用监听端口，不要求启用内置 Web Channel。对外回调地址、平台应用设置、验签和用户授权由部署方及适配器负责。安装、配置、多实例、开发契约和可安装示例见 [自定义 Channel 接入](../development/channel-plugins.md)。

## 配置 Bot 和持久化

以 SQLite 为例，在 Bot 的 endpoints.yml 中保留：

```yaml
base_store:
  type: sql
  dialect: sqlite
  db: workspace/sessions.db
```

该路径相对于 Bot 目录。个人 Bot 和小型单进程服务可使用 SQLite；其他 SQL 后端配置见 [Endpoints](../configuration/endpoints.md)。
无 Store 配置时可能使用 MemoryStore，它不能跨重启保留历史。每个独立 Bot 部署使用自己的数据库或存储命名空间。

模型凭据写入 `llms`，渠道凭据写入 `channels`。先用 shell 验证，再开启外部入口。
训练型 Policy 在启动前执行 train/--check；缺失或过期索引会使加载失败。

## 单进程启动

```bash
cota run --config ./my-bot --chat-app --host 127.0.0.1 --port 5005
```

`cota run` 使用单执行进程；不同会话有限并发、同会话顺序执行。
不要通过 Gunicorn 多 worker 或多副本同时消费同一会话：当前没有跨进程执行租约，SQL revision 也不能撤销已经发生的外部副作用。
如需进程守护，使用部署环境自己的服务管理工具，确保不会启动重复执行实例。

## 公网入口与授权

对外服务通常在前面放 HTTPS 反向代理，并代理 HTTP 与 `/ws` WebSocket 到同一个 Cota 监听端口。
代理应支持 WebSocket Upgrade 和长连接，不把 Debug 端口暴露出去。
也可使用 CLI 的成对 `--ssl-cert`、`--ssl-key` 配置直接 TLS。

跨源网页需在 `channels.web.cors_origins` 中列出完整 origin，例如 `https://chat.example.com`；不使用通配符或带路径 URL。
CORS 不替代身份鉴权。自己的应用应通过 ExternalAccess/access_factory 完成 token 验证和会话成员授权。
配套聊天应用则提供自己的访客身份与成员管理。

临时演示可使用 `--tunnel localhostrun`、`--tunnel cloudflared` 或 `--tunnel ngrok`，依赖相应外部命令与服务。
它们不提供 Cota 托管、访问控制或可用性保证。日常部署不应依赖临时地址。

## 健康、投递和关闭

`GET /api/health` 检查 Application 和启用通道的就绪状态；不请求模型，不代表模型供应商或业务工具一定可用。
使用代表性问题另做业务验证。

运行 completed 表示执行完成，不表示使用者收到回复：

- Web：从持久历史按游标补取；断线不会重跑模型。
- 飞书：保存回复和投递记录，按目标顺序重试；平台接受不等于用户已读。
- 自定义 Channel：声明持久化投递能力的适配器复用同一套补发机制；平台支持时用稳定的 event_id 去重。

退出时 Application 停止接受输入并有界等待/清理。成功接收的输入已持久化；重启时有界恢复尚未开始的 direct 输入。客户端未收到确认时仍使用原 message_id 重试；已经开始但中断的操作不能盲目自动重跑。
详见 [应用契约](application.md) 与 [回复投递](delivery.md)。

## 备份与升级

备份 Bot 文件、训练产物和持久 Store。启用聊天应用时，还需保留 `.cota/chat.sqlite3`、`.cota/chat.key`；使用核心 GuestAccess 时保留 `.cota/web.key`。
数据库运行中使用相应数据库的一致性备份方式；不要只复制 SQLite 主文件而遗漏正在使用的 WAL 状态。

升级先在副本验证配置、Policy 和代表性对话，再停止旧实例并加载新版本。
当前大版本不兼容旧 Event/Store schema，遇到 schema 错误不要直接在有价值的生产库上删除数据。
若只是可丢弃的本地试验，可停止进程、备份后移走旧数据库，再使用新库。
Snapshot 缓存版本不匹配通常可从事件重建，与事件表 schema 不兼容是两回事。

部署选择的配置入口见 [部署配置](configuration.md)，交付责任见 [分享](sharing.md)，异常排查见 [故障排除](troubleshooting.md)。
