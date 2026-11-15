# Pi compaction budget and error boundary

User-approved scope: remove the Cota 2000-token summary cap, preserve Pi's compaction APIs and provider options, distinguish execution failures from transport failures, and verify failure behavior without adding a second loop or task scheduler. Execute inline with TDD and verification-before-completion; retain the previous interrupted-run changes.

- [x] Add failing regressions for native/custom summary budgets, truncation, input plus output capacity, typed worker errors, and diagnostics/user-visible stopped execution.
- [x] Forward Pi summary options through the existing native provider/custom adapter; validate input against the actual summary output allowance. Continue using Pi's safe cuts and summary validation.
- [x] Use one small execution-error contract (`code`, `phase`, `error_type`, optional `request_id`) across worker/Python. Reserve PiBridgeError for framing/protocol/connection failures; do not change the wire format or add new Event types/tables.
- [x] Preserve terminal error fields and show a clear stopped message after successful persistence; never retry failed commits or replay tools. Mark truncated summary diagnostics rejected while retaining the actual provider response and HTTP status.
- [x] Run local Node/Python regression and full suites; update runtime/debug documentation and record evidence here. Do not call paid endpoints, alter private Bot configuration/history, or push unrequested changes.

## Budget clarification

Cota's default main reply limit is 500, so it cannot double as the summary allowance. The summary model receives an independent `compaction.max_tokens` budget, defaulting to `min(8192, reserve_tokens)`, validated against reserve space. Pi still owns the prompts, cuts, serialization and rejection of length-stopped summaries. No custom compactor, new model provider or retry loop is introduced.

## Verification evidence

- Red tests reproduced the original 2000-token truncation, lack of typed error metadata, insufficient summary input/output capacity accounting, conflation with PiBridgeError, and waiting for stderr EOF after stdout closed.
- Native and Python-adapter summary output budgets, independent short-reply defaults, full worker/Processor truncation with Debug on/off, unchanged history, no invalid compaction checkpoint, and durable user-visible stopped execution are covered with local fakes.
- Targeted Python regression: **111 passed** (`/tmp/cota-summary-python-target-final.log`); final config/progress checks: **38 passed**.
- Full Node suite: **199 passed, 2 skipped** (`/tmp/cota-summary-node-full.log`).
- Full Python suite: **1833 passed, 2 skipped**, 28 existing dependency warnings, 379.43 seconds (`/tmp/cota-summary-python-full.log`).
- Ruff (`cota tests`) and `git diff --check` passed.
