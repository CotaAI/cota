# Runtime integration implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. Do not delegate or commit without a user request.

**Goal:** Integrate the existing uncommitted execution recovery and compaction fixes with the current file-driven Policy/Knowledge tools and per-type Events.

**Architecture:** Cota owns durable Events, executor ownership, budgets and error presentation. Pi owns the single model/tool loop, native transport and public compaction algorithm. Retrieval remains an on-demand tool with `details.hits`; no automatic Policy selector, new Event type or compatibility layer is restored.

**Tech Stack:** Python 3.12, SQLite/MemoryStore, Node, Pi 1.4.0, pytest, node:test, Ruff.

## 1. Reconcile tests and contracts

- [x] Run `pytest -q tests/test_read_resources.py tests/test_run_metadata.py`; capture the four obsolete Policy assertions before editing.
- [x] Replace removed `_policy_guidance()` assertions with existing Skill read/Trace and replay assertions. Replace `agent.policy` discovery expectations with catalog persistence independent of retrieval failures.
- [x] Add a real KnowledgeTool/PolicyTool regression for `details.hits` through Runtime, Store replay and a subsequent native request. Exercise `rerank: true` in a multi-tool batch using a local model server.
- [x] Remove only unused imports reported by `ruff check cota tests`.

## 2. Integrate runtime and documentation

- [x] Audit `runtime/execution.py`, Store admission, PiBridge FD inheritance and typed errors, Event validation, independent compaction output budgets and Pi option forwarding against the current implementation. Fix only integration failures exposed by the regressions.
- [x] Keep the current source selection `prepared.messages ?? messages` and structured retrieval details. Store original results; summarize only old-run request projections.
- [x] Update the runtime/DST/configuration docs and their README, tutorial, CLI and Policy references to describe on-demand retrieval, canonical prepare projection, execution ownership, summary failure semantics and the independent summary budget. Remove obsolete auto-selection/training/knowledge-template claims and unused sample policy configuration.

## 3. Verify

- [x] Run focused integration tests (native requests, metadata, ownership, compaction, retrieval, Store/DST recovery).
- [x] Run `.venv/bin/python -m pytest -q`, `npm test` in `cota/runtime/pi`, `.venv/bin/ruff check cota tests`, and `git diff --check`.
- [x] Review the combined diff; no live model calls, private Bot configuration changes, database migration, commit or push.

## Verification results

- Baseline: `pytest -q tests/test_read_resources.py tests/test_run_metadata.py` exposed four obsolete automatic-Policy assertions (4 failed, 24 passed).
- Focused: `pytest -q tests/test_retrieval_runtime.py tests/test_read_resources.py tests/test_run_metadata.py` — 32 passed. Four new real-Pi retrieval tests cover Memory/SQLite and normal/Debug modes, auxiliary rerank origin, multi-tool results, replay and later request projection.
- Full Python: `.venv/bin/python -m pytest -q` — 1818 passed, 2 skipped, 28 warnings in 357.20s. Includes ownership, native requests, compaction and recovery tests. Log: `/tmp/cota-runtime-integration-full-python.log`.
- Full Node: `npm test` in `cota/runtime/pi` — 199 passed, 2 platform-dependent skips, no failures. Log: `/tmp/cota-runtime-integration-full-node.log`.
- Ruff and `git diff --check` passed. Modified Markdown local links checked; no missing targets. mdBook is not installed, so no rendered documentation build was performed.
- All model traffic in tests used local substitutes; no live provider calls or private Bot/data changes. Local executor recovery remains limited to verifiable POSIX local Store ownership, not distributed leases.
