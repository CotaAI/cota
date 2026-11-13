# Context budget and overflow recovery

Goal: Keep long tasks within an explicit working context budget while reusing Pi's public threshold, estimation, compaction and overflow classification APIs.

Architecture: Agent Core remains the only model/tool loop. Cota supplies a working threshold and commits compaction before the next model call. Native context-overflow recovery invokes Pi continuation once, with no replay of committed tools. No AgentSession, private Pi imports, new event types, paid calls or live project/database writes.

- [x] Add failing tests in `cota/runtime/pi/context.test.mjs` for a 64k working threshold independent of a 1M model capacity, bounded retention, and renewed usage calibration after historical image projection stabilizes.
- [x] Extend `compactionSettings` with `trigger_tokens` (default 64000, clamped to available input); default retention is min(12000, half the working threshold). Continue calling Pi `shouldCompact` with the effective budget without changing the provider model capacity.
- [x] Add a compact image-projection fingerprint in `image-context.mjs`. Carry it on assistant origins through `pi_trace.py`, native and Python observations and `events/assistant.py`, so restored runs can validate the latest usage without storing messages again. Test replay, native and fallback paths with Debug off.
- [x] Add failing native SSE tests in `model.test.mjs`: a context overflow compacts and retries once; prior tools are not replayed; a repeated overflow, cancellation, exhausted decision budget or failed checkpoint stops; ordinary provider errors never invoke compaction.
- [x] Use Pi `isContextOverflow` in `model.mjs`, retaining safe diagnostic errors. Let `engine.mjs` skip the failed assistant fact, force Pi compaction at its existing prepare boundary, and call Agent Core continuation once. Python custom/RAG adapters retain their existing failure behavior; no Python error-pattern matcher is added.
- [x] Validate `trigger_tokens` in `cota/config.py`. Extend existing compaction event with optional reason and token count, and Debug request budgets with threshold/retention. Reject impossible fixed instructions or current image batches explicitly. Test that guidance is re-prepared and never summarized.
- [x] Update configuration, runtime, execution-flow and Debug docs. Run Pi tests, affected Python integration/replay tests, Ruff, diff checks and the full Python suite. Preserve existing raw evidence and credentials. Do not commit or push unless requested.

Acceptance: the existing 1M-capacity configuration compacts around its working budget; valid post-projection usage is used again; failed provider responses never become bot/tool facts; original successful tool executions happen once across recovery; Store acknowledgment remains a prerequisite to further work.

Verification: Python full suite 1784 passed / 2 skipped; Node suite 192 passed / 2 skipped; Ruff and git diff --check passed. Native SSE, Python adapter, replay, cancellation, decision limits and compaction commit failure were exercised with local controlled providers. No paid model requests or live project writes.
