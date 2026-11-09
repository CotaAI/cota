# Stable DST Trace Implementation Plan

> Execute with test-driven-development and subagent-driven-development. The user approved a breaking cleanup; preserve unrelated worktree changes and do not commit or publish.

**Goal:** Give Cota a versioned, ordered execution record and a multi-Skill trace projection while Pi remains the execution engine.

**Architecture:** Stable Cota events carry an envelope (schema_version, event_id, sequence, timestamp, run_id, type, source) and typed payloads. DST holds events and replaceable execution checkpoints; Store persists both. Tool result checkpoints are acknowledged before Pi continues. Trace projects calls by (run_id, tool_call_id), distinguishes historical Skill reads from evidenced associations, and keeps annotations separate from facts.

**Tech Stack:** Python, Pi Core/Coding Agent 1.4.0, Node JSONL bridge, pytest, node:test.

- [x] Define and test versioned event serialization, monotonic sequences, validation, reset and round trips. Retain useful Python user/bot accessors; reject old serialized envelopes.
- [x] Add trace projection and Store event/trace queries. Test multiple reads, cross-run references, duplicate call phases, pending/blocked/error calls and annotations.
- [x] Normalize runtime callbacks into run_started/run_finished, model_response, context_prepared/context_compaction, skills_loaded, tool_started/tool_result/tool_finished, skill_read/resource_read events. Remove implicit last-read attribution. Preserve result-before-ACK checkpoints.
- [x] Enrich Pi reads with resource owner, requested range and content hashes from bytes actually read. Preserve Pi reader, path boundaries and fatal checkpoint behavior.
- [x] Delete unused SkillMemory and overwrite-mode LoopDebugger; update consumers, exports, examples, tests, installation smoke and docs. Preserve UserMemory, policies, tool adapters and checkpoint recovery.
- [x] Run focused red-green tests, full Python/Node suites, independent spec and quality review, package build and installed-wheel smoke. Record exact results below.

## Contract

Event construction supports `Event(type=..., payload=..., run_id=..., source=...)`; named user/bot/read/tool-result classes are conveniences. `Event.as_dict()` returns only the new envelope and payload. Event payloads preserve native JSON result content, including empty values. DST assigns sequence at append and validates restored sequences/IDs/schema. `active_skill` is a last-read marker, reset explicitly, never tool ownership.

Runtime event payloads: `tool_started` has tool_call_id/tool/arguments; `tool_result` has tool_call_id/tool/arguments/raw_result/model_result/is_error; `tool_finished` has tool_call_id/tool/is_error/duration_ms/result_event_id (or model_result for Pi-blocked calls with no result callback); `skill_read` has skill/tool_call_id/path/resource/hash/range; `resource_read` has resource-owner metadata and tool_call_id. `run_started` references input_event_id and previous_run_id; `run_finished` has status/error_type. `model_response` preserves the model reply once; message_end updates checkpoints without duplicating it as a public trace event.

Trace associations reference Skill read event IDs and tool calls with an explicit basis. Resource ownership is evidence only of file ownership. Model/heuristic/manual associations are separately identified; no automatic claim that subsequent tools used the last-read Skill. No automatic RSI, side-effect replay, compatibility migration or new runtime engine.


## Verified completion

- Python full suite: **553 passed, 7 skipped**, 64.23 seconds. Existing pytest/dependency deprecation warnings remain.
- Node worker and Skill resources: **15 passed**, including staged bundled Node/Pi dependencies.
- Independent spec and quality reviews completed. Findings fixed with observed red-green regressions: native raw values, incomplete/conflicting tool facts, type-sensitive immutable Store comparisons. Final reviewer independently ran **92 focused tests**.
- Built macOS ARM64 wheel and sdist. Installed-wheel smoke passed without system Node/npm or network: CLI, hello/pet/weather templates, real Pi loop, Skill source hash and stable trace projection. Model/network responses were mocked.
- Wheel inspection confirmed current Store/Pi source, new trace modules, and absence of deleted SkillMemory/debugger/native npm helpers.
- Removed old SkillMemory, LoopDebugger, orphan debug_state/max_history/mock Skill registry, global debug_log route and implicit last-read tool ownership. Public event helper is ToolResultEvent.
- Added append-only delivery receipts and immutable persisted facts; preserved UserMemory, business policies, tool adapters and failure recovery.
- `git diff --check` passed. No commits or publication; unrelated prior worktree changes preserved.

Remaining boundaries: SQLStore still stores whole-session JSON snapshots; queries paginate after loading. Model/heuristic annotations and automated RSI are not generated. Old DST v2 snapshots are rejected, not migrated. External effects are not guaranteed exactly once; interrupted/uncertain runs still require explicit reconciliation.
