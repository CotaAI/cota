# Cota Channel 插件示例

独立安装的通用 Webhook/REST 适配器。它演示可信网关协议，**没有实现 SeaTalk 或其他真实平台的原生 API**。

在运行 Cota 的同一个 Python 环境中，从仓库根目录安装：

```bash
python -m pip install ./examples/channel-plugin
```

安装只注册 `cota.channels` entry point，不会自动启用插件。将下列片段并入 Bot 的 `endpoints.yml`：

```yaml
channels:
  office_im:
    enabled: true
    type: example_im
    app_id: app-one
    webhook_secret: replace-with-random-webhook-secret
    api_base: https://gateway.example/v1
    api_token: replace-with-outbound-api-token
```

`office_im` 是实例名，回调路径为 `POST /channels/office_im/webhook`。若实例直接命名为 `example_im`，可省略 `type`。使用当前 Cota 源码时，应先在相同环境安装该源码版本，再安装示例。

网关用 `webhook_secret` 对**原始请求体字节**计算 HMAC-SHA256，将小写十六进制摘要放入 `X-Signature`；请求体示例：

```json
{"user_id":"alice","chat_id":"room-one","text":"你好","message_id":"platform-event-one"}
```

可选 `mentioned`（布尔）、`sender_name`、`reply_to` 由可信网关生成。Cota 的 `dialogue.mode` 决定 direct/group。网关负责平台认证、授权、群成员与真实 @Bot 判断；外部用户不能直接指定可信身份。

成功返回 `202` 和持久化 receipt，模型可能仍在执行。`503` 要求发送方使用**原 message_id 和原内容**重试，`409` 表示同一 ID 的内容冲突。配置 SQL Store 才能在进程重启后保留接收与投递记录。

回复发送到 `POST {api_base}/messages`，携带 Bearer token 和 `Idempotency-Key: <event_id>`，JSON 为 `app_id/chat_id/text/event_id`。网关必须按 event_id 去重，并用非 2xx 表示失败；插件不自行重试。生产部署使用 HTTPS，保管密钥并保护出站网关。协议不含挑战应答、原生附件、token 刷新或真实平台的签名规则，应按目标平台补齐。

完整开发契约见 [Channel 插件开发](../../docs/src/development/channel-plugins.md)。在仓库根目录运行协议测试：

```bash
.venv/bin/pytest -q tests/channels/test_example_plugin.py
```
