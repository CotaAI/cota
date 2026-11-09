# Incremental context and optional model diagnostics

**Goal:** Restore model context from durable facts and disposable snapshots, without repeated whole-context events.
**Architecture:** DST projects user/model/tool/compaction facts into context_messages. Pi consumes and extends this projection using stable event identities. Store keeps optional model_debug records outside the event sequence. Request preparation remains dynamic; Policy fingerprints accompany model outcomes.
**Execution:** Implement inline in the existing development workspace; preserve unrelated changes. No legacy event compatibility or automatic data deletion.

- [x] Add recovery tests covering tool batches, failed reads, compaction boundaries, snapshots, multiple turns, debug parity and durable output before effects.
- [x] Replace execution_updated and lifecycle messages with a deterministic context projection. Remove obsolete event types and references. Record compaction replacement IDs and summary exactly.
- [x] Persist one normalized model outcome per call. Keep provider request/response and preparation details in an optional Store diagnostic record with request_id. Failures in diagnostics must not affect execution; failures in core checkpoints must stop execution.
- [x] Update Pi callbacks to exchange single-message identity acknowledgements instead of context snapshots. Inject fresh prompt/Policy at each prepareRequest.
- [x] Add Memory/SQL diagnostic persistence and read-only Debug request detail access; keep Events faithful to the core event stream.
- [x] Update contract tests and documentation, run Python and real Pi tests, inspect frontend syntax and packaging sources. Verify no obsolete production emitters remain.

Validation: .venv/bin/python -m pytest tests/; node --test cota/runtime/pi/worker.test.mjs; node --test tests/debug/viewer.test.mjs; node --check cota/debug/static/app.js; git diff --check.

Validation completed: 767 Python tests passed in the sandbox; the 5 local socket/process tests passed on a permitted rerun (772 passed total, 8 skipped). Pi worker: 15 passed. Debug JavaScript: 1 passed. Live temporary Debug page verified core Events, independent model diagnostics and restored DST context; no provider network calls.
