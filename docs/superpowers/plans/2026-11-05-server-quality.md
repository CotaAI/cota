# Server stability and usability

**Goal:** Make the existing single-process public server easier to integrate and reliable at admission, readiness, failure and shutdown boundaries.

**Architecture:** Keep HTTP configuration/routes/lifecycle in server.py. WebService remains the shared authenticated submission/notification adapter for HTTP and WebSocket; Application owns execution, deduplication and history. No new event, table, chat management API, sync model endpoint, or raw trace exposure.

**Scope and choices:** Add POST messages (202 admission receipt and Location pointing to existing receipt endpoint) rather than a second blocking chat implementation. Keep existing /version and history/receipt routes; do not add redundant status aliases. Readiness returns 503 when starting/stopping or a configured channel is absent/down; it never invokes an LLM. Expose only safe channel status, retaining exception details in logs. Strict early config validation and consistent JSON HTTP errors reduce deployment ambiguity. Retain one shutdown task enclosing Application then WebService cleanup even if a listener waiter is cancelled.

## Tasks

- [x] Write real HTTP tests for nonblocking submission, authorization, generated IDs, cross-transport deduplication/conflicts, invalid bodies, backpressure, readiness, JSON failures and encoded identifiers. Confirm missing behaviors fail before implementation.
- [x] Validate agent/channel/CORS settings before creating the Sanic app; retain current defaults and explicit origin policy. Add constructor regression tests for invalid types and unsupported settings.
- [x] Add POST /api/conversations/<session_id>/messages. Only text, message_id, mentioned, reply_to allowed; identity comes from Bearer authorization and URL. Call WebService.submit, return receipt and encoded Location. Never await execution. Map conflict to 409, busy to 429 + Retry-After, unready to 503, validation to 400, denied access to 403, unexpected failure to safe JSON 500. Preserve useful framework status/headers (404/405/413 etc.).
- [x] Add Application.accepting_messages property; readiness includes lifecycle and all enabled channels. Add GET history until_sequence to expose the existing bounded snapshot pagination argument. Include Location in allowed-origin response headers.
- [x] Cover shutdown with cancelled listeners and failed Application close; use one shielded teardown task for Application then WebService, without task leaks or premature observer cancellation.
- [x] Update public API docs with curl submission and poll/history flow, error table, request constraints and deployment lifecycle. Run focused integration tests then full Python/JS regressions, compile checks and diff check. Preserve unrelated working tree edits; no commit.

## Verification

Targeted regression: 67 passed. New tests first reproduced missing submission/readiness/config behavior, cancelled shutdown ordering, and HTTP 500 during authentication/admission shutdown races. Tests use real local listeners/SQLite/Pi with deterministic models, not live provider calls. JavaScript regressions: 41 passed. Python compileall passed. Full Python regression: 993 passed, 1 skipped (170.72 seconds). Final Content-Type normalization was additionally verified by all 24 new server contract tests. Existing dependency/fixture deprecations and the CustomLLM destructor cleanup warning remain outside this server change; no failed tests. Final diff check passed.
