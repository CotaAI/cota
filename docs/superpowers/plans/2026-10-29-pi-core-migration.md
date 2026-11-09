# Pi Core migration implementation plan

**Goal:** Keep Cota's Bot definitions, policies, DST and Store authoritative while delegating the model/tool loop to Pi Agent Core.

**Architecture:** Python coordinates business state, tools, model adapters and persistence. A version-pinned Node worker runs Pi Core over an acknowledged JSON-lines protocol. The worker has no session files or database; Cota stores execution events and a replaceable model-context projection separately from user-visible history.

**Tech stack:** Python asyncio, SQLAlchemy, Node >= 22, @earendil-works/pi-agent-core 1.4.0.

## Implementation and verification

- [x] Add regression tests for detached snapshots, optimistic revisions, conversation queries, execution state round trips and legacy snapshots. Run `pytest tests/test_store.py tests/test_dst.py` before implementation; verify the new assertions fail. Implement DST execution checkpoints and event identifiers; keep existing SQL table compatible, use atomic compare-and-swap and move SQL I/O off the event loop.
- [x] Add real Pi worker integration tests with deterministic Python model responses (no external model credentials): tool dispatch, changing tool visibility, schema rejection, pause with multiple tool calls, restart, model failure, iteration cap, cancellation and persistence failure. Run these before adding the bridge.
- [x] Add `cota/runtime/pi/` with exact npm dependencies and lockfile, a worker module and Node tests. Add `pi_bridge.py` for process lifetime, request IDs, bounded waits, error propagation and cleanup. Model and tool requests remain Python callbacks; Pi owns the loop.
- [x] Add `pi_runtime.py` for context projection, policy injection, skill lifecycle and checkpointing. Keep raw user text separate from policy material. Retain Cota's skill loader; do not import AgentSession merely for helpers. Preserve full execution events even when projecting a bounded model context. Refuse automatic replay of interrupted side effects.
- [x] Switch Processor's default to Pi, keep explicit `dialogue.runtime: legacy` for rollback, serialize same-session work, save inbound input before execution, avoid sending an older turn's response and preserve real-time replies in history. Test both Channel and MessageBus paths.
- [x] Document installation, configuration, persistence/recovery boundaries and migration. Run Node tests, targeted Python tests, broader relevant regressions and inspect the diff. No live model requests, external sends or publishing are part of this migration.

## Deliberate limits

This change does not create a hosting platform, sandbox image builder or autonomous RSI release service. It establishes the runtime/persistence boundary needed by those features. No exactly-once external effects or distributed session leases are claimed. Historical sessions remain readable; unresolved tool effects require explicit reconciliation instead of blind replay. Compression and skill loading helpers from Pi remain optional integrations, not a reason to take on AgentSession.


## Verification outcome (2026-10-29)

- Full Python suite: 476 passed, 7 skipped. Existing pytest-asyncio, Sanic and legacy LLM-test warnings remain. The WebSocket start test requires permission to bind a local port and passed outside the filesystem/network sandbox.
- Real Pi Core Node suite: 6 passed. Python integration tests also launch the real worker with deterministic model/tool callbacks; no live provider requests were made.
- Built sdist and wheel with `uv build`; verified worker and exact npm lockfile are included, node_modules and Node tests excluded.
- `python -m cota.runtime.pi_setup --check`, compile checks and `git diff --check` passed.
- Independent read-only review found two compatibility issues (unconsumed observation events and screenshot forwarding). Both were reproduced, fixed and re-reviewed with regression tests; no remaining important findings.
- Memory/SQLite persistence tested; MySQL DDL compiled with LONGTEXT, but no live MySQL/PostgreSQL deployment was tested.
- Existing untracked advanced scenario tests were retained. Only the DPL-injection assertion in `tests/integration/test_advanced_scenarios.py` was adjusted to the new separate-guidance contract.
- Work remains uncommitted on feature/2.0. No deployment, publishing, paid model calls or database migrations were performed.
