# Native Pi model calls and streaming implementation plan

**Goal:** Run ordinary OpenAI-compatible conversation and compaction requests in Node through Pi, with Python Policy hooks, durable traces, and transient public streaming.

**Architecture:** Cota restores event-backed context and sends the resolved endpoint once. Pi owns provider serialization, streaming and the model/tool loop. Python remains the authority for Policy, authorization, attachments and committed execution facts. Explicit Python custom/RAG adapters retain their existing transport and do not pretend to stream.

**Tech stack:** Python asyncio, Pi 1.4.0, Node provider hooks, existing Channel/WebSocket contracts.

- [x] Native provider: add real local SSE tests; replace the ordinary model RPC with Pi native streaming; carry deadline, retry, thinking and image limits; use the same transport for summaries. Observe payloads only in Debug; retain safe timing/usage normally.
- [x] Model observation: export resolved endpoint configuration without logs, stage completed native assistant decisions before durable events; record request failures without introducing new core events.
- [x] Bridge: independently drain requests and transient notifications with bounded queues; preserve acknowledged execution checkpoints, cancellation and stdout backpressure. No full final context returned by production worker.
- [x] Policy/context: avoid round-tripping image bytes for native requests; prepare from the durable projection and return system guidance/tools; resolve incoming files through authorized references.
- [x] Channels: add optional transient stream capability for Web and cmdline; route on the existing session binding; do not put deltas in Events/outbox or retry them. Link final delivery to request identity to avoid duplicate display; indicate interruptions.
- [x] Regression: test greeting, mixed text/tools, multi-turn restore, Policy between tool calls, failed commits, cancellation, image budgets and Debug. Run full repository checks and update runtime/channel documentation. No paid provider calls, private Bot changes, commits or push.

## Validation evidence

- Real Node subprocess against local SSE: greeting arrives before completion, restores cleanly on the next turn, and never calls Python's dialogue model.
- Mixed commentary and tool calls: public text commits/publishes before effects; a failed checkpoint prevents every tool effect; next Policy sees committed tool evidence.
- Real local multimodal picture-book chain: nine native main-model requests, official Bash, image generation/editing, vision review, PDF build and generic attachment delivery. Scripted local providers validate protocol and execution, not actual creative quality.
- Native provider tests cover retry limits, whitespace keepalive timeout, stalled Debug hooks, truncated calls, summary streaming, image hydration and worker cancellation.
- Channel tests cover bounded previews, per-frame authorization, session binding, late deltas, empty tool-only previews, final replacement and cmdline deduplication.
- Packaging input/required-file validation now includes model.mjs; installed smoke consumes status/events rather than redundant final messages. No wheel artifact was built.
- Independent review found and verified fixes for stalled-hook deadlines and empty tool-only previews; final spec and quality verdicts passed.

Final repository check (`scripts/check.py`): 272 source files syntax-valid; Ruff passed; Python 1577 passed, 2 skipped (28 existing warnings), 327.55s; Node 130 passed, 2 skipped, 0 failed. The additional installed-smoke regression was collected after that full run and passed in the focused distribution suite (12 passed). Final diff whitespace check passed. No paid provider inference, private Bot changes, wheel build, commit or push.
