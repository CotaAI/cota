# Runtime context and stable request prefixes

Goal: Cota supplies business guidance as request-local Pi custom content, with no vendor branches and no new conversation events.

- [x] Add failing native/fallback tests for stable system/tools, current-only tail guidance, unchanged raw history and budget inclusion.
- [x] Split Python prepare into stable system + runtimeContext, sort selected Policy display without changing ranked selection; move dynamic template data, knowledge, memory and group trigger into runtime context.
- [x] Use Pi transformContext + official convertToLlm for one ephemeral custom message. Keep execution counters out of ordinary requests; preserve tool schemas in wrap-up with tool_choice none and execution blocking.
- [x] Canonicalize image markers and content ordering across Node execution and Python recovery; keep raw evidence and current pixels, never add wrap-up notices to old image messages.
- [x] Record cache-read/miss usage and lightweight static input fingerprints in Debug; avoid claiming server-side cache guarantees.
- [x] Run relevant Python/Node regressions, update architecture/debug docs with exact runtime flow. No paid model calls, no edits to live session/project data.

Non-goals: no Pi source edits, no AgentSession adoption, no persistent guidance transcript, no rewritten compaction algorithm or cache-warming requests. Compaction/config/model/permission changes are explicit prefix boundaries.

Verification: Python full suite 1769 passed / 2 skipped; Pi Node suite 179 passed / 2 skipped; Debug viewer 8 passed; Ruff and git diff --check passed. All model boundaries were controlled local fixtures; no paid model calls or live project data changes.
