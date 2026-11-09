# Assistant Event Carriers Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for isolated test/docs tasks and review. Existing user-authorized dirty feature/2.0 workspace is authoritative; no bulk commits or unrelated changes.

**Goal:** Remove model_response while restoring Pi context solely from business/tool events and preserving direct Debug request access.

**Architecture:** bot/tool_started own normalized assistant messages; subsequent tool starts and tool-generated utterances reference existing events. Runtime stages model decisions until the first carrier, commits it before execution, and acknowledges its identity to Pi. Diagnostics remain independent.

**Tech Stack:** Python/pytest, Pi Agent Core JavaScript/Node tests, SQLAlchemy SQLite/Memory Store, vanilla Debug viewer.

- [x] Add tests/test_assistant_carriers.py covering the approved contracts; run to observe missing-carrier failure.
- [x] Add cota/events/assistant.py for carrier shape/reference validation and message projection. Update event.py/context.py/trace.py/DST snapshot version and PolicyContext.
- [x] Update observation.py and pi_trace.py to stage decisions, count requests, write carriers and link diagnostics; update pi_runtime.py/engine.mjs to acknowledge durable IDs and remove final-response duplication.
- [x] Update Debug Inspector/UI to resolve request diagnostics through carrier/tool references, including error/pending records without carriers.
- [x] Migrate old model_response test fixtures/assertions and documentation; preserve behavioral coverage.
- [x] Run targeted tests, then full Python and Node suites. Fix failures and review invariant coverage. Mark completed only with fresh results.

## Verification and review

- Initial new carrier tests: 6 failures before implementation, then 6 passes.
- Migrated behavior tests: 175 passed (/tmp/cota-carrier-migrated-tests.log).
- Runtime/replay/processor contract regression: 80 passed (/tmp/cota-carriers-regression2.log).
- Full Python run: 815 passed, 8 skipped, 5 sandbox failures (/tmp/cota-carriers-full.log). All five loopback/process-inspection tests passed with required permissions (/tmp/cota-carriers-permitted.log).
- Final targeted regression after review fixes: 161 passed (/tmp/cota-carrier-review-final.log). Tests include forged Policy attribution, nullable metadata, missing batch links, multi-tool durability, cross-run references, Debug parity and snapshot suffix recovery.
- Node worker + viewer: 17 passed (/tmp/cota-carriers-node.log).
- Independent spec review passed; independent quality review identified two issues, both fixed and re-reviewed with 8 focused tests passing.
- No changes to user databases, no old-event migration, no branch merge or commit. Snapshot schema is now 4.
