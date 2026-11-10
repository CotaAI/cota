# Pi context budget and focused guidance implementation plan

**Goal:** Complete the approved context optimization: use Pi compaction, account for images separately, focus business guidance, and expose request costs without changing durable execution facts.

**Architecture:** A small Node adapter uses public Pi `estimateTokens`, `shouldCompact`, `findCutPoint`, and `compact` APIs. Cota supplies model limits and summary transport, validates and commits exact-prefix compaction events, and rebuilds guidance after compaction. No AgentSession or Pi session files are introduced.

**Tech stack:** Pi 1.4.0, Python asyncio, SQLite/MemoryStore, existing read-only Debug UI.

- [x] Add failing Node tests for image estimation, same-user-turn cut points, summary cancellation/failure, and safe retained tool batches. Add Python tests for replay and provider usage propagation.
- [x] Add `cota/runtime/pi/context.mjs`; wire model preparation and summary RPCs into `engine.mjs` and `pi_runtime.py`. Remove Python `_compact` and the JSON-character budget. Configure token limits with `llms.<name>.context_window` and `dialogue.compaction.{reserve_tokens,keep_recent_tokens}`; use Pi model metadata or a documented conservative fallback when capacity is unknown.
- [x] Carry real provider usage into normalized assistant messages; invalidate usage estimates across compaction boundaries. Validate summary prefix against current DST and checkpoint before continuing. Reject truncated/empty summaries without changing history.
- [x] Test and implement Policy focus rendering that retains preceding user and result conditions without injecting unrelated later steps. Use the existing BM25 strategy for the picture-book example, with a small candidate budget and explicit training instructions.
- [x] Improve the picture-book Bot prompt and CLI help so normal generation does not require reading implementation source. Preserve the portable Skill and private endpoint credentials.
- [x] Add bounded request-size/usage diagnostics and show running elapsed time, actual input/cache/output/reasoning tokens and estimated context sections in the existing Debug request tab. Keep estimates distinct from provider measurements.
- [x] Migrate affected tests/docs/configuration; run targeted tests, the original image/context regression through real Pi with controlled model responses, and the full repository checks. Sync only relevant Bot files to the private deployment; do not generate paid images or restart user services.

Authorization: user approved the preceding design and requested implementation in this conversation. Execute inline; no additional design approval or git publication is requested.

## Verification

- Final `scripts/check.py`: 262 source files passed syntax/Ruff; 1,499 Python tests passed (2 skipped); 95 Node tests passed (2 skipped). Log: `/tmp/cota-context-release-check.log`.
- Coverage across the complete suite and refreshed group fixtures: 87.58%.
- Real Pi controlled tests cover same-user-turn compression with a real PNG, Memory/SQLite snapshots and event-only replay, summary rejection/cancellation, stale usage, and changing instruction budgets.
- The original failed checkpoint was replayed read-only: its 2,167,812 image Base64 characters contribute an image estimate, with a total request estimate of 27,103 tokens rather than a JSON-character overflow.
- Picture-book initial-query guidance: 8 whole cases / about 3,089 characters became 3 candidates / 1,497 characters. This is an input-size comparison, not a measured real-model latency claim.
- Private picture-book config/help/docs and BM25 artifact updated; endpoints checksum unchanged, Skill identical to source, doctor ready. No paid-model requests, user-service restarts, commits or pushes.
- Independent read-only review identified an instruction-delta budget issue; a failing regression was added and corrected with a documented conservative system/tool reserve. Summary input preflight also rejects imported history that cannot fit its own request.
