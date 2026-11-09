# Proactive group participation quality

**Goal:** Improve timely unsolicited participation without stale decisions, duplicate interruptions, or delaying explicit requests.

**Architecture:** Group intake remains durable and independent of execution. One bounded background consideration per group coalesces messages, applies a short judgement interval and an actual-utterance cooldown, then submits approved work as background priority to Runner. Runner preserves FIFO within explicit work, never preempts already-running tools, and prefers queued explicit work. Revalidate the approved conversation sequence in the execution slot and atomically when committing the first execution checkpoint. Pi remains responsible for Skill choice and execution; a tool-free ParticipationJudge only decides whether intervention is useful.

**Defaults:** 1 second quiet window, 3 second maximum merge window, 2 second judgement interval, 60 seconds since the last actual Bot utterance, 10 second judgement timeout. No user-facing YAML additions. @ messages bypass participation/cooldown and invalidate pending unsolicited decisions. New ordinary input invalidates stale decisions and schedules consideration of the latest context. Negative/failed judgements never impose the speech cooldown. Pending sessions bounded by Runner.max_pending; judgement concurrency bounded by Runner.concurrency. Background capacity exhaustion may skip participation while preserving all inputs.

**Scope:** Keep existing Events, Store schema, direct behavior, and explicit mention FIFO. No autonomous timers without an input, distributed workers, RSI, provider-specific heuristics, or interruption of already-started side effects. Deterministic scheduling/prompt tests are behavioral regressions, not evidence of measured live model accuracy.

## Tasks

- [x] Add priority-aware bounded Runner admission and explicit-work query, with tests for FIFO, priority, cancellation and shutdown.
- [x] Refactor GroupConversation into bounded latest-input coalescing workers; lifecycle cancellation; separate monotonic judgement throttling from persisted Bot utterance cooldown; no per-message dormant tasks.
- [x] Add a tool-free ParticipationJudge, bounded structured transcript and capability metadata; reuse Pi discovery via a read-only bridge operation, no Python Skill parser or SOP injection. Cache immutable catalog per Application lifetime; restart to refresh.
- [x] Recheck source sequence after judgement and on execution admission/start; suppress cancelled/answered/stale work, prioritize @ inputs, and retain actual execution futures through newer messages.
- [x] Tests: NO then new actionable input, quiet/max merge, superseded YES, human answer/retraction arrives during judge, @ during slow judge, queued background priority, actual utterance cooldown including restart, failed/silent runs no speech cooldown, queue saturation, duplicate and shutdown behavior, debug request/no fake events, capability filtering.
- [x] Update group/deployment docs, run focused and full regressions, obtain independent spec and quality reviews. Preserve pre-existing uncommitted work and do not commit unrelated changes.

## Review and verification

- Independent specification review passed; deployment documentation was updated to match the implemented defaults and boundaries.
- Independent quality review passed after fixing queued, active-prestart, and shutdown receipt races. The new regression first reproduced each failure before the fix.
- Focused scheduling/lifecycle suite: 40 passed. Final full Python regression: 969 passed, 1 skipped (165.76 seconds). The suite reports dependency/fixture deprecations and a CustomLLM cleanup warning; no failed tests.
- JavaScript worker/client/UI suite: 41 passed. Python compilation and `git diff --check` passed.
- No live model-provider or Feishu requests were made; real participation accuracy still requires representative group conversation samples.
