# Web 聊天入口

当前 Cota 使用可选聊天应用提供浏览器入口，不再读取 `front.md` 或通过模型生成 HTML。

```bash
cota run --config ./bots/weather --chat-app --port 5005
```

打开 `/chat/` 即可使用聊天页面。应用提供访客身份、会话列表、单聊/群聊、邀请和断线恢复；
数据与签名密钥保存在当前 Bot 的 `.cota/` 下，不随 `cota init` 或模板发布复制。

`cota/webapp` 管理这个配套应用，`cota/channels/web` 管理传输与接入协议；
业务执行仍通过 Application、Processor、DST/Store 和 Pi Core 完成。
外部网页或小程序可以实现自己的身份、会话管理和 UI，再对接 Web Channel。

- [可选聊天应用](../deployment/chat-app.md)：启动、数据与访问管理。
- [Web 接入协议](../deployment/api.md)：HTTP、WebSocket 与重连。
- [应用接入契约](../deployment/application.md)：身份、会话归属、提交与执行状态。
