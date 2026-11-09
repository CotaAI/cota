# Reliable reply delivery implementation plan

**Goal:** Recover committed Feishu replies after send failure/restart without executing the model or tools again.
**Architecture:** Store atomically appends bot_utter and lightweight delivery rows in the same database. A bounded delivery dispatcher reads only each target's oldest undelivered row, reconstructs text from immutable events, sends via Channel, and records success/backoff/failure. Web continues cursor recovery. No delivery Events or DST state. Single executing process per Store remains required.
**Authorization:** User approved preceding design and requested implementation. Preserve current dirty workspace; no commits or live external messages.

- [x] Storage tests first: Memory/SQLite atomic append, idempotent save, transaction rollback, restart recovery, oldest-target ordering, bounded queries, retry state. Implement delivery_store.py helpers and Store.save(delivery_target=None), with a new deliveries table automatically created.
- [x] Dispatcher tests first: offline retry, independent target progress, ordered same-target delivery, exhausted failure/manual retry, cancellation/restart, persistent acknowledgment failure without immediate resend. Implement channels/delivery.py. Defaults: 8 concurrent sends, 10-second send timeout, 8 attempts, exponential delay 1 to 300 seconds, 0.25-second poll. Channel-specific stable UUID remains unchanged.
- [x] Integration: Application sets an explicit trusted delivery target only for channels opting in (Feishu); Processor passes it to Store checkpoints and suppresses volatile reply publication for that target. Manager owns dispatcher lifecycle and drains bounded sends before adapter stop. Graceful Runner shutdown lets active turns finish within existing deadline; queued input still not durable. Feishu application scope must match recovery targets.
- [x] Query/retry API: trusted Application.delivery_status(session_id, event_id) and retry_delivery(session_id, event_id). Failed head blocks later target replies until explicitly retried; other targets continue. Status means platform accepted, not human read. No public admin HTTP endpoint.
- [x] Acceptance: real Processor/Pi with deterministic model + SQLite, network send mocked. Stop after reply commit/send failure, reopen Store/new app, resend original event, assert model call count unchanged. Check outbox creation failure rolls back reply event. Check Web remains cursor-based and no outbox rows for SDK/Shell/Web.
- [x] Full Python and JS regression, docs, diff/compile checks. Delivery is at least once; stable platform IDs mitigate but do not eliminate ambiguous-send duplicates. MemoryStore cannot survive process exit. No durable inbox, multi-process leases, groups, fanout or delivery of non-event notifications.


## Verification

- Full Python regression: 947 passed, 7 skipped (139.50 s).
- Final targeted regression after persisted-attempt budget fix and Feishu diagnostics: 58 passed, including 20 storage, 6 dispatcher, 2 SQLite/Application recovery, 12 Feishu, 18 scheduling tests.
- JavaScript Web/Pi: 19 passed.
- Spec review found and verified fix for retry budget across interrupted sends; final quality review approved.
- Existing dependency deprecations and unrelated LLM test warnings remain. No live provider or platform sends performed.
- compileall and git diff --check passed. No commits; pre-existing workspace changes preserved.
