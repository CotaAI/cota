# Trusted inputs and Store-owned deduplication implementation plan

**Goal:** Remove mandatory Web identity/ownership/receipt tables, accept externally authenticated conversation identities, and make input deduplication/status channel-independent with generated message IDs when omitted.

**Architecture:** Existing user_utter and run events are the durable truth. Store coordinates live admissions in memory and derives durable receipts from events. No new tables or event types. Queued is explicitly volatile; committed input is never automatically executed twice after restart. Processor owns generic durable-input checks; Runner owns generic queue claims. Web accepts trusted identities through injected authenticate/authorize callbacks. Optional stateless signed guest adapter preserves standalone sharing without identity tables. Private SDK calls already trust their caller.

**Tech stack:** Python asyncio, existing Store/SQLAlchemy, Sanic, Pi, browser JavaScript.

- [x] Core: tests first for generated IDs, concurrent duplicate admission, content/user conflicts, durable receipt reconstruction, no new tables, same input on multiple Channels, no automatic replay after interrupted run. Modify Store/input helper, Processor, Runner and message envelopes. Keep session FIFO and cross-session concurrency.
- [x] Web: remove WebRepository. Inject external identity and authorization adapter; optional signed standalone guest adapter is isolated from Store. Service delegates receipts/claims to Store/Runner. Preserve authorized history, reconnect and stable delivery.
- [x] Client: external token/session mode skips guest/conversation provisioning; omitted message ID server fallback; standalone mode retained. Update protocol docs, tests and obsolete imports.
- [x] Verification: targeted Store/execution/Web tests, real socket acceptance, JS tests, full suite, diff check. Review only this change; preserve existing dirty work, do not commit.

Identity adapter must authenticate token and authorize user/session on every application entry. External identities are never accepted raw from public browsers. Standalone signing secret is file-backed for restarts, not a database table. Explicit adapter/external mode disables guest provisioning. Existing obsolete web tables are left untouched in existing databases, but new installations never create or query them.

## Verification results

- Final full Python suite: 904 passed, 7 skipped (pre-existing warning categories remain).
- Pi/debug/Web JavaScript suites: 20 passed.
- Real localhost HTTP/WebSocket tests cover external auth/session ownership, generated input IDs, restart receipts, concurrency, reconnect, and failure before commit. Models are deterministic mocks; Pi and persistence execute normally.
- Spec and quality review complete; all findings resolved, including stalled-executor observer shutdown.
- Compileall and git diff --check passed. No database migration, added tables, external model calls, or commits.
