# Long-task context and picture-book reliability

> Execute inline with superpowers:executing-plans and test-driven-development. Preserve existing workspace changes; no delegation, commit or paid model calls.

**Goal:** Correct repeated Pi compaction, simplify the example Bot's review contract and make rendered text readable.

**Boundary:** Pi owns cutting and summarization. Cota supplies the previous summary and raw delta, saves Events and exposes model text. The Bot owns editorial criteria, review evidence and deterministic PDF layout. Deferred consolidated questions remain supported.

## 1. Context integration
- [x] Add failing Node regressions for a previous Cota summary plus raw work and a later user decision; assert Pi receives previous-summary separately, no nested historical_summary and complete replacement IDs.
- [x] In `cota/runtime/pi/context.mjs`, separate the latest `cotaCompaction` message, pass its text as `previousSummary` to Pi compact, cut only the raw tail, include the prior summary ID in the committed replacement prefix. Keep cancellation, budgets and tool-pair behavior.
- [x] Run context and engine tests; add a short public-text convention to the default prompt, preserving ordinary progress and deferred questions.

## 2. Bot review and revision contract
- [x] Add failing tests in `tests/test_picture_book_tool_reviews.py` for importing prompt/image/output from an actual call, explicit reasoned criteria revisions and invalidation of prior passes.
- [x] Make redundant review CLI fields optional; derive them from committed evidence. Keep explicit provided-field validation, model/image hashes and immutable reports. Add `--criteria-change-reason` and append criteria history without deleting old evidence. Publish one exact response schema in CLI help.
- [x] Replace the local PDF three-version/frozen-page rejection with version tracking and exact-image acceptance. Paid image budgets remain separate. Update rendering regressions to verify changed pages invalidate evidence and unchanged builds stay reused.
- [x] Condense `agent.yml`; align Policy and README on required checks versus defaults/advice, honest delivery, no hand-copied bookkeeping and no Shell exit-status masking.

## 3. Readable deterministic typography
- [x] Add failing layout/render tests for dark artwork with protected text, explicit transparent background, padding bounds and insufficient solid-color contrast.
- [x] Support `background` (default ivory; null explicitly transparent) and `padding` in text elements. Draw the panel before text, measure the inner text box, hash all rendering inputs and retain change-only rendering. Reject invalid geometry and poor foreground/panel contrast.
- [x] Update build help and Bot instructions: reserve composition space, use protected typography, review actual rendered pages; do not fix layout by repeatedly regenerating illustrations.

## 4. Verify and synchronize
- [x] Run focused Bot tests and full Node/Python suites, Ruff, diff checks; render a dark-background fixture and inspect it visually.
- [x] Back up changed files in `cota_projects/picture-book`, synchronize definition/code only, preserve endpoints/workspace/.cota and custom retrieval top_k. Verify isolated loading, real Pi discovery, retrieval and local build without provider calls.
- [x] Record actual verification results and remaining limitations here.


## Verification results

- Red/green: both repeated-compaction regressions failed on the original implementation, then passed; context suite 24 passed.
- Red/green: inferred review inputs/CLI, reasoned criteria revision, fourth local layout correction and text-panel rendering regressions failed before their implementations, then passed.
- Full Python: `.venv/bin/python -m pytest -q` — 1829 passed, 2 skipped, 28 dependency deprecation warnings in 358.68s. Log: `/tmp/cota-book-reliability-full-python.log`.
- Full Node: `npm test` in `cota/runtime/pi` — 201 passed, 2 platform skips, no failures. Log: `/tmp/cota-book-reliability-node.log`.
- Ruff (framework, tests and changed Bot code) and `git diff --check` passed. Checked 180 local documentation links without missing targets.
- Rendered and visually inspected a local sample with real existing artwork and protected Chinese vector text at `/tmp/cota-readable-sample/workspace/books/readability/previews/pages/page-1.png`; original artwork and book were not modified.
- Backed up and synchronized nine picture-book definition/code files to `cota_projects/picture-book`. Backup: `/Users/mingguang.shao/work/cota_projects/.backups/cota-adaptation-20261115-095615`. Verified file equality (preserving top_k=3), endpoint hashes, isolated load, Pi discovery and retrieval. Bot now carries 15 Policy cases and 13 evaluation cases / 15 turns; new evaluation data was parsed, not run against a paid model.
- No paid provider calls, original project/database edits, commit or push. Existing PDFs need a fresh build and corresponding reviews; contrast panels do not replace checks for covering important subjects. Local production records remain editable by the machine account and are audit records, not tamper-proof authorization.
