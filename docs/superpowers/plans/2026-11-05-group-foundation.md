# Common group conversation foundation

> **For agentic workers:** Use superpowers:subagent-driven-development for implementation and independent spec / quality reviews. Existing feature/2.0 work is uncommitted; preserve it and do not commit unrelated changes.

**Goal:** Persist authorized group conversation independently of Bot execution; passive mentions and opt-in proactive participation use shared application scheduling, speaker-aware context and safe memory boundaries.

**Architecture:** Agent dialogue.mode selects direct/group (default direct); dialogue.response selects passive/proactive (default passive; direct always responds). Trusted input carries mentioned boolean and optional speaker display name / reply reference. Group reception commits user facts before scheduling. Execution uses a detached DST view tied to the triggering message and merges only newly generated events into current canonical history under short Store locks. Runtime never replaces newer incoming messages. Receipt distinguishes recorded input from execution. No room/member UI or distributed workers.

**Tech Stack:** Python asyncio, existing Memory/SQL Store, Pi Core bridge, existing Web/Feishu adapters.

## Tasks
- [x] Persistence: add short-locked event append / execution delta commit, preserve immutable IDs, revision checks, outbox atomicity, snapshots; tests for incoming messages between checkpoints and restart/replay.
- [x] Contract: validate mode/response; migrate old mode=agent examples to direct; trusted mentions / sender labels / references participate in deduplication; direct context remains plain.
- [x] Coordination: group intake persists independently, schedules explicit mentions; normal group input returns recorded with no run. Admission and callbacks remain bounded and retry-safe. Platform bus goes through Application intake.
- [x] Runtime / DST: stable trigger, speaker-aware group projection, fixed execution context, no private memory tools/context in groups; compacted summaries retain attribution; canonical replay supports interleaved user and execution facts.
- [x] Proactive: bounded per-session coalesced evaluation, conservative model yes/no decision, fixed cooldown, mentions bypass; no tool execution during participation decision; failures remain recorded and logged.
- [x] Adapters: trusted SDK/Web access contract for mentions (no body matching), Feishu group parsing with verified bot identity; mode mismatch rejected; public history includes speaker where required. Cmdline direct only.
- [x] Verification: targeted tests first, full Python regression, JS tests, config/docs examples, independent spec and quality review. Test group receive during blocked model/tool, snapshot/replay and delivery identities.

## Acceptance
Two users share group history; ordinary messages persist without Pi; a mention produces one correctly attributed reply using earlier group history; new arrivals during the run persist immediately and do not enter that run; retries do not duplicate facts or executions; private personal memory is unavailable. Direct chat retains existing prompt shape and behavior. Both MemoryStore and SQLite pass deterministic mocked model tests.


## Implementation notes
- Passive reception uses user_utter only; recorded receipts survive restart without fake run events.
- Event merge preserves original IDs and canonical Store sequences; runtime context is detached.
- Late explicit retries retain dependencies of prior trigger AND context-boundary references, freeze a fresh view, and still target the original request.
- Proactive judgement has independent debug diagnostics, no run, conservative yes/no and bounded cooldown/coalescing. Its context includes recent user and bot messages.
- Web group mode requires external authorization. No group/member UI added. Feishu bot identity comes from official bot-info API.
- Channel retry buffer is bounded, and stop cancels it; no implicit restart replay.
- Spec review approved (64 focused tests); independent quality review approved after default-mode and optional-description regressions were fixed.
- Latest targeted run: 54 passed (group, CLI shell, example bots, configuration). JavaScript: 22 passed.

## Final verification
- Full Python suite after all fixes: 911 passed, 1 skipped (154.16s). Existing deprecation and LLM-test cleanup warnings remain.
- JavaScript client/Pi worker suite: 22 passed.
- compileall and git diff --check passed.
- Spec review and code quality review approved; review findings reproduced with failing regressions before fixes.
- No live Feishu messages or real model-provider requests were sent. No commit created.
