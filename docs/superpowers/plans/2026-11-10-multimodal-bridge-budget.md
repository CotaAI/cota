# Multimodal bridge and byte-budget repair

**Goal:** Resume large multimodal histories without hitting asyncio's line limit, and keep active model requests bounded using Pi compaction.

**Evidence:** Picture-book run 71413590e20345d7ab929ab8d57fd4ae stopped after event 159 (successful title-image read). Event 160 reports ValueError: Separator is not found, and chunk exceed the limit. Event-only replay produces 144 messages and 16 image blocks; the prepare RPC alone is 35,285,951 bytes (33.65 MiB), above the bridge's 32 MiB readline limit. The preceding model request succeeded at 56,600 input tokens against a Pi catalog capacity of 1,000,000. No image generation or provider-context failure caused this termination.

**Design:** Keep the acknowledged JSON-lines protocol. Read each frame incrementally with a small pipe buffer and an explicit 128 MiB frame ceiling, apply the same ceiling to outbound frames, and reject incomplete/invalid frames with safe PiBridgeError messages. Independently cap serialized active model context with dialogue.compaction.max_request_bytes (default 32 MiB). Token or byte pressure invokes Pi's existing cut-point and summary APIs; when the retained suffix is too large, reduce Pi's recent-token target until a complete tool batch fits. Persist the existing context_compaction event before continuing. Never erase raw events, trim an image silently, or retry tools/model generation automatically.

- [x] Add failing real-subprocess bridge tests for >32 MiB bidirectional payloads, explicit byte limits, truncated frames and checkpoint failure.
- [x] Implement bounded incremental JSON-lines transport without changing Pi execution or adding dependencies.
- [x] Add failing byte-driven Pi compaction tests, including token-small/image-large histories, complete retained tool pairs and an unsplittable recent image.
- [x] Add serialized-byte accounting/configuration and wire byte-triggered compaction into existing prepareRequest. Expose the budget in existing Debug diagnostics.
- [x] Exercise real Pi with controlled PNG results and Memory/SQLite replay; replay the failing history offline with controlled model responses only.
- [x] Document transport vs token vs serialized-byte budgets and run focused/full checks. Preserve private endpoints, generated images and the original Store; no paid generation or automatic user-service restart.

The separate observation that a shell pipeline masked an earlier build error is not the cause of this termination. Record it as a follow-up; do not change Pi's native shell semantics or silently rewrite model-generated commands.

## Verification and review

- Before implementation, the real 33 MiB subprocess round trip and protocol edge tests failed (four failures, one existing behavior passed). Both real-Pi PNG byte-budget regressions also failed because no summary ran. All three initial Node byte cases failed. Logs: /tmp/cota-large-bridge-red.log, /tmp/cota-byte-runtime-red.log, /tmp/cota-byte-budget-red.log.
- Independent review found that a paused stdout buffer could hang cleanup after an oversized frame. A 1 MiB output / 1 KiB frame-limit test reproduced a timeout; finally now drains stdout concurrently with shutdown. The reviewer's no-newline/sleeping worker returns its original error in about 2.07 seconds after the fix.
- Review also found a false attachment budget for text-only models. Python now supplies the same MIME/size hydration policy used at the provider boundary; Node reserves bytes only for images actually eligible for injection. Tests cover vision:false, eight vision:true PNG references and unsupported SVG MIME. Default budget is 32 MiB so a valid eight-image input is not rejected solely because of its Base64 encoding.
- Focused Python: 31 passed, three dependency deprecation warnings (/tmp/cota-multimodal-final-focused.log). Node context: 13 passed (/tmp/cota-byte-budget-final.log). Reviewer reran bridge 6/6 and context 13/13 and closed both findings.
- Read-only replay of the original 160 events: initial working context 35,285,882 bytes, then one Pi summary (83,871-byte text-only request) and one controlled main request (25,949,369 bytes, 11 retained images). Completed with state equal after MemoryStore reload; source DB and artwork were never written, and no paid inference/generation ran. Evidence: /tmp/cota-original-history-replay.json.
- Final full scripts/check.py: 263 first-party sources passed syntax and Ruff; 1,507 Python tests passed (2 skipped), 100 Node tests passed (2 skipped), exit 0. Log: /tmp/cota-multimodal-full-check.log. git diff --check passed. No commit/push or user-service restart was performed for this repair.

## 2026-11-11 main integration

- User requested fetching, merging and publishing main. Fast-forwarded to upstream 6408a32, verifying that all thirteen local repair files were byte-identical before and after the merge.
- Preserved upstream generic REST endpoints and Debug styling/navigation. Restored model request summaries, request-size/context-budget cards and efficient running-request refresh that upstream had removed; retained the new four-tab HTML and removed stale store/log-path element accesses.
- Viewer tests now use the real HTML ID set, and a mutation regression catches references to the removed sidebar fields. Seven focused UI tests pass.
- Upstream management routes initially violated the existing public-server execution-boundary test. The routes are now opt-in through create_app(session_api_authorize=...), with authorization owned by the embedding application and an explicit True required for every read. No Cota accounts, credentials or tables were added. Five real HTTP boundary tests pass; docs describe activation and all retained paths.
- Final merged-tree verification: scripts/check.py passed syntax/Ruff for 264 sources, 1,511 Python tests (2 skipped), and 101 Node tests (2 skipped), exit 0. Log: /tmp/cota-merge-final-20261111-check.log. Independent read-only review found no outstanding integration issues; encoded-path probes did not bypass management authorization. Credential/large-file scan and git diff checks passed before publication.
