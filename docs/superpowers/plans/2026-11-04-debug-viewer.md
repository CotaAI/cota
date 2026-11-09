# Local Debug Viewer Implementation Plan

> Execute inline against the current feature/2.0 workspace, preserving existing changes. The user approved the design and implementation; no separate approval or commit is needed.

**Goal:** `cota shell --debug` starts a local, read-only browser viewer for the current session, with incremental events, linked execution details and explicitly sourced DST views.

**Architecture:** A small aiohttp service (already a dependency) shares the Shell Store and a getter for its latest Processor. Store exposes bounded event headers and session metadata; full facts and state are fetched on demand. Static HTML/CSS/JS ships inside the wheel. No Runtime callbacks, debug database, frontend build or production server lifecycle is introduced.

**Scope:** Timeline, run selection, full event details and links, persisted/live/snapshot state. Read-only HTTP; loopback + per-process capability URL and same-origin checks. Poll only headers; no full-state polling. Browser errors and startup failure do not abort Bot execution. Exit closes service and consumers.

- [x] Add failing tests for Memory/SQLite header pagination, lightweight SQL projection, metadata without history loading, immutable inspector reads and missing/live/stored state distinctions.
- [x] Implement Store read APIs and `cota/debug/inspector.py`; reuse SQLStore._io for blocking database reads and offload persisted-state reconstruction.
- [x] Add failing HTTP tests for read-only routes, invalid query bounds, token/Host/Origin protection and failure isolation. Implement `cota/debug/server.py` with aiohttp AppRunner and loopback ephemeral port, no scheduler or model initialization.
- [x] Implement `cota/debug/static/{index.html,app.js,style.css}`. Three-column layout, incremental cursor, run/timeline/raw views, lazy detail, linked model/tool events and three labeled state sources. Use textContent for all captured content; pause hidden-page polling and avoid overlapping requests.
- [x] Add Shell lifecycle tests. Expose the channel session key and wait-for-close; retain latest Processor locally, start debug service only for --debug, close it on /stop/EOF/cancellation. Keep --log independent of --debug.
- [x] Run focused Python tests, JavaScript syntax/unit checks and real HTTP/browser smoke; verify static package inclusion. Run full suite and recheck any sandbox-specific failures with authorized system access.
- [x] Document startup, data sources, supported views and initial scope. Review for write paths, data-source ambiguity, oversized polling and cleanup errors.

Validation commands: `.venv/bin/python -m pytest tests/test_debug_viewer.py tests/test_debug_shell.py tests/test_execution_logging.py tests/test_store.py tests/test_event_sourcing.py -q`; `node --check cota/debug/static/app.js`; `.venv/bin/python -m pytest -q`; `git diff --check`.


Verification evidence:
- Focused regression (Store, DST, logging, Shell, templates): 95 passed, 1 skipped.
- Full suite: 759 passed, 8 skipped; 5 failures were sandbox-denied socket/process operations only.
- Final permitted rerun of Debug/Shell plus those system tests: 28 passed, 1 skipped, including two added long-ID regression cases. Aggregate Python coverage: 766 passed, 8 skipped.
- JavaScript projection tests: 3 passed. JavaScript syntax and git diff whitespace checks passed.
- Real browser: model request and Policy link, Skill path and tool-result links, Store/live/snapshot sources checked; live-only event #13 correctly absent from committed event #12. No browser errors.
- Offline sdist built; all three static assets verified byte-for-byte in the archive. Release wheel/runtime bundling was not changed.
- Temporary browser demo and early failing test processes cleaned up. No commit or push.
