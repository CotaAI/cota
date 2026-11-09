# Event-sourced DST Implementation Plan

**Goal:** Rebuild every serialized conversation-state field from ordered events, with disposable snapshots.

**Architecture:** DST.apply_event is the only state reducer used by live execution and replay. Runtime emits execution changes and Pi observations. Store appends one row per event, manages optimistic revisions separately, and optionally saves the latest state snapshot at execution boundaries or after 100 events. Loading applies only the suffix after a valid snapshot; absent/invalid snapshots trigger full replay. Existing consumers still receive complete history, so history hydration is not yet lazy.

**Tech Stack:** Python, SQLAlchemy (SQLite/MySQL), pytest, official Pi Core bridge.

User approved this design in the conversation. Implement in the existing dirty feature branch without unrelated edits or commits. Old snapshot schema is rejected; do not silently import incomplete historical state or delete existing databases.

- [x] Add failing tests: event-only identity/context/vars/pause/Pi checkpoint/reset reconstruction; detached values; replay at every prefix.
- [x] Add typed state events and deterministic reducer, state snapshot encoding and validation; route state setters and Runtime writes through events. Event timestamps supply created_at/updated_at; session_id is stream identity, revision is Store metadata, agent is injected.
- [x] Add failing persistence tests for per-event rows, snapshot thresholds and boundaries, suffix-only reducer use, missing/corrupt snapshot fallback, stale writers, rollback.
- [x] Replace whole-DST persistence with sessions metadata, events and session_snapshots; shared Memory/SQL behavior, explicit Store.load, direct SQL event/history queries.
- [x] Test actual Pi pause/resume, errors and checkpoints using event-only replay; run relevant suites and full regression.
- [x] Document mutation APIs, physical schema, snapshot cadence, recovery limitations and incompatible schema handling.

Validation commands:
`.venv/bin/python -m pytest tests/test_event_sourcing.py tests/test_dst.py tests/test_runtime_persistence.py tests/test_store.py -q`
`.venv/bin/python -m pytest -q`

Assertions compare state_dict() across every persisted prefix and snapshot+tail, not just as_dict/from_dict roundtrips. Store revision is compared separately. Replay must not contact UserMemory, models or tools.


## Validation results

- New event-sourcing suite: 35 cases, including real Pi read/pause/resume, every checkpoint replay, numeric timestamp SQL roundtrip, corrupt/missing/versioned snapshot fallback, all terminal boundaries, stale writers and transaction rollback.
- Focused reducer/runtime regression after execution-shape validation: 90 passed.
- Final full suite: 707 passed, 7 skipped; four additional tests require permission to bind a local port or execute ps. Their isolated unrestricted rerun passes (4 passed).
- Existing warnings concern pytest-asyncio fixtures and unrelated LLM test cleanup.
- `git diff --check` passes. No remote model calls, database migrations, commits or unrelated cleanup.
- MySQL table DDL is tested, but no live MySQL server was available for integration testing.

The snapshot optimizes reducer replay; full history hydration/validation remains for current Trace/Policy consumers. Legacy sessions.data is rejected without deleting the database.
