# Application contract and Feishu private chat implementation plan

**Goal:** Expose a small stable application API over existing execution and validate it with Web and official Feishu private-text ingestion.

**Architecture:** Application owns ChannelRunner lifecycle and presents submit/history/status results, preserving Store-based dedup and Processor/Pi. Web delegates trusted execution to Application after access checks. CLI can load a deployment-provided access factory and can run Feishu without enabling Web chat. Feishu uses official lark-oapi long connection in an isolated Python process (SDK owns its event loop); Cota maps im.message.receive_v1 private text into scoped IDs and sends text to the original chat using official REST with stable UUID.

**Scope:** No new tables/events, group replies, media processing, persistent delivery queue, multi-process execution leases or live platform sends without user-provided test authorization. Preserve current dirty workspace; no commits.

- [x] Application: tests first; new cota/application.py, public exports; one runner, trusted submit_message and keyword submit, Submission wait/receipt and per-run public messages; lifecycle/context manager; histories shared with Web; service-mode user execution. Hook existing Runner handler rather than another execution loop.
- [x] Web/CLI: delegate to Application; optional channels.web.access_factory module:callable validated early; support channels.web.enabled=false with no public chat/guest routes; explicit all-disabled error, reliable health and Channel readiness. Include importable application integration example.
- [x] Feishu: replace unverified manual WS protocol. Official SDK worker stdio acceptance acknowledgment, bounded stop, no credential argv/logging; correct official event fields, p2p/user/text only, app+tenant user/session scope, raw chat_id routing, source message_id retained, rejected/unsupported events ignored. REST text send receive_id_type=chat_id, code/status validation, token lock, stable event UUID, bounded transient retries and clear failure logs.
- [x] Tests/docs: actual SDK model parsing and process handshake without live platform; duplicate/private isolation and committed-reply tests with real Runner/Store/Pi deterministic model; full Python/JS checks. Document permissions/subscription/install, application ownership and delivery limits.

## Public API agreed for implementation

Application(agent, channels=None, concurrency=8, max_pending=256); .runner/.store; await start(configure=None); await close(); async context manager.
await app.submit(user_id=..., session_id=..., text=..., message_id=None) -> Submission.
await app.submit_message(inbound, on_input=None, on_reply=None) -> Submission (adapter integration).
Submission: .session_id, .message_id, .future, .duplicate; await receipt(); await wait() -> {receipt, messages} (messages only this input and its run's bot utterances; wait is shielded).
await app.history(session_id, after=0, limit=100, until=None) -> {messages,cursor,through,has_more}; await app.receipt(session_id,message_id).
No authentication inside trusted Application; Web adapters and platform adapters establish identity first. Queue admission remains volatile; persisted input prevents reexecution.


## Verification

- Full Python regression: 919 passed, 7 skipped (141.21 s); existing dependency deprecations and unrelated LLM test warnings remain.
- Web client and Pi worker JavaScript: 19 passed.
- Focused contract/Feishu acceptance: 39 passed, including real official SDK parsing/process lifecycle with substituted network.
- Spec review and subsequent code quality review approved; fixed cancellation teardown and transient token-fetch retry issues during review.
- uv lock --check --offline, compileall, example --help, git diff --check passed.
- No live Feishu send or model-provider call performed. Operator still needs to configure credentials/platform permissions and verify real account delivery.
