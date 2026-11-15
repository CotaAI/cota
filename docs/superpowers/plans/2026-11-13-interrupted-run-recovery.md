# Interrupted Run Recovery Implementation Plan

> Execute inline using TDD and verification-before-completion. The user approved the minimal design; no automatic task replay or distributed scheduler is included.

**Goal:** Let a new explicit user message continue a session whose local executor has exited, without replaying unknown tool effects.

**Architecture:** Local file-backed SQLite and MemoryStore bind each Pi run to a nonblocking OS file lock. Python holds the lock throughout execution and passes its descriptor to Pi, so a surviving worker still prevents takeover. A small executor identity on `run_started` binds recovery to the same host and Store scope. Under that lock, recover only the matching persisted running run by appending the existing `run_finished(status=interrupted)`. Missing ownership, another host, unsupported backends and a held lock fail closed. Normal load/receipt lookups never change execution state.

**Tech Stack:** Python asyncio, POSIX flock/pass_fds, existing DST/Store/Event, pinned Pi worker.

## Tasks

- [x] Add failing tests for cross-Store exclusion, isolated sessions, reopening SQLite, orphan reconciliation, immutable unknown tool evidence, live-worker descriptor inheritance and new-message continuation.
- [x] Add a small execution ownership module and Store guard/reconciliation helpers. Keep lock files stable and never unlink them during release; close descriptors without unlocking locks still held by Pi.
- [x] Hold ownership in PiAgentRuntime, attach its identity to run_started, and inherit the descriptor in PiBridge. Ensure exceptions and cancellation release resources.
- [x] Reconcile at new-input admission/Processor loading, never when retrying an old message_id or reading history. Reuse the existing terminal-event projection and Pi loop.
- [x] Document local-only recovery, no unknown-call retries, and conservative behavior for historical/unowned or remote runs.
- [x] Run regression suites for runtime/bridge/recovery/application/Store/group execution, then full Python/Node suites and lint/diff checks. Record actual results here. No paid model calls or private Bot changes.

## Acceptance

1. A live Python or inherited worker lock prevents reconciliation and a second executor.
2. After both exit, a new explicit input records exactly one interrupted terminal fact and proceeds.
3. Successful tool results survive; missing results remain unknown and are never manufactured or retried by recovery.
4. Store loads, startup recovery and duplicate submissions do not automatically rerun a started input.
5. Unsupported ownership is rejected rather than presumed stale from elapsed time.

## Verification

- Initial red tests reproduced missing executor ownership/recovery. Identity validation and SQLite `db=None` each received an additional red/green regression.
- Runtime/bridge/recovery/Application/persistence/run-metadata regression: **125 passed** (`/tmp/cota-execution-recovery-target-final.log`).
- Final ownership and bridge checks: **47 passed** (`/tmp/cota-execution-owner-final.log`), including actual SIGKILL of Python with a surviving Node lock holder, new-message continuation through Application and Processor, duplicate input, failed commit, stale revision, remote ownership rejection and isolated ephemeral SQLite instances.
- Pi Node suite: **192 passed, 2 skipped** (`/tmp/cota-interrupted-recovery-node-full.log`).
- Full Python regression: **1808 passed, 2 skipped**, 28 existing dependency warnings, 378.08 seconds (`/tmp/cota-interrupted-recovery-python-full.log`). The additional identity/ephemeral-SQLite/stale-revision regressions were verified in the final 47-test targeted run.
- Ruff for `cota tests` and `git diff --check` passed.
- All model responses were fakes/local tests. No paid endpoint requests, private Bot updates, Pi SDK patches, new Event types or database tables.
