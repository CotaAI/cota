# Web conversations implementation plan

**Goal:** Two users chat with one Bot through WebSocket with isolated identity/history/memory, ordered turns, concurrent sessions, and reconnect recovery.

**Architecture:** One Sanic HTTP/WebSocket listener; Web application service owns guest credentials, conversation ownership and durable input receipts. Channels remain adapters. A bounded per-session runner feeds independent Processors. Replies are published only after Store commits and replayed from Store with stable event IDs. No new DST event types, multi-process leases, group membership or automatic replay of interrupted tools.

**Tech stack:** Python asyncio, Sanic, existing SQLAlchemy Store/MemoryStore, Pi Core, plain browser JavaScript.

- [x] Execution context and publication: isolate bound tools; move memory I/O off the event loop; commit before publishing every bot utterance; preserve Shell behavior. Files: processor.py, runtime/pi_runtime.py, executor/tools, executor/user_memory.py; focused regression tests.
- [x] Scheduling: bounded per-session FIFO with cross-session concurrency, result futures and managed shutdown; explicit channel lifecycle and queue closure. Files: channels/runner.py, manager.py, queue.py, events.py; concurrency/lifecycle tests.
- [x] Web application: persisted hashed visitor credentials, conversation ownership, input idempotency receipts and authorized message history. New web repository/service modules with SQL and memory tests.
- [x] Transport and server: mount /ws in Sanic, authenticate first frame, reconnect replay plus live subscription, isolated connection send queues, protected HTTP APIs; remove obsolete public tracker/SSE paths from this serving surface. Update CLI assembly.
- [x] Browser client: persistent visitor/session identity, reconnect/backoff, stable submission IDs, history/live deduplication, minimal working chat page.
- [x] Verification/documentation: real localhost sockets with deterministic model responses and temporary SQLite; test isolation, parallel turns, order, reconnect, duplicates, persisted publication and failure handling. Run relevant then full regression. Document protocol and single-process limitations.

No repository-wide cleanup, commits, or compatibility aliases are required. Preserve unrelated working-tree edits.

## Verification

- Full Python regression: 880 passed, 8 skipped; existing warnings remain.
- Additional real HTTP metadata regression after replacing an obsolete skipped test: passed.
- Pi worker, debug viewer and Web client JavaScript tests: 19 passed.
- Browser verification: first turn retained after refresh; second turn continued the same conversation.
- Compileall and git diff --check passed. No live external model provider was called; acceptance tests used deterministic model responses with the real Pi loop, HTTP/WebSocket listener and SQLite persistence.
