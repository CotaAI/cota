# Picture-book convergence implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. Preserve pre-existing working-tree changes; no unrelated Runtime/Pi edits or live paid calls.

**Goal:** Enforce the already-approved two-revision rule and stable review evidence in the portable picture-book Bot.

**Architecture:** `bookbot/production.py` holds only project-scoped command serialization, stable asset validation, generation-journal accounting and fixed review metadata. Existing `models.py` owns requests and immutable outputs; CLI exposes compact blocked outcomes/status. Pi remains the only agent loop, Cota retains existing Events.

**Tech Stack:** Python standard library, existing HTTPX/Pillow, YAML policies, pytest fake model endpoints.

## 1. Generation budget, test first

- [x] Create tests/test_picture_book_convergence.py with real PNG bytes/HTTPX stub. Call generate with `asset='page-04'` and three distinct prompts/outputs; fourth changed output must raise a structured nonretryable block before HTTP. Another asset must still work. Identical completed inputs under a renamed output must reuse bytes and consume no attempt. Unknown prior outcome must block a renamed retry.
- [x] Run `.venv/bin/pytest -q tests/test_picture_book_convergence.py -k generation` and observe missing-contract failures.
- [x] Add project lock/asset validation/journal accounting to bots/picture-book/bookbot/production.py. Require asset on models.generate; preserve standard provider handling and reserve `asset`, `attempt`, status before the paid call. Fail with ProductionBlocked when count reaches 3 or an earlier outcome is unknown.
- [x] Migrate existing direct test calls to explicit stable asset IDs. Re-run new and existing picture-book tests.

## 2. Stable review, test first

- [x] Add a vision stub that returns different text per call. Two reviews of the same image/criteria under changed outputs/aliases must call it once and preserve original labels. Changed pixels call it again. Changed criteria, corrupted evidence and unknown previous requests block without HTTP.
- [x] Run focused tests and observe the current filename-only cache failure.
- [x] Store fixed criteria and canonical versioned review records in .bookbot. Cache by model, fixed criteria and ordered byte hashes, excluding alias paths. Keep original content/labels as evidence and explicit reuse provenance; do not infer QA pass from prose.
- [x] Verify locks reject concurrent same-project reservations and are released after errors.

## 3. CLI, guidance and integration

- [x] Require `--asset` on generate/review; print ProductionBlocked details with nonzero exit. Add per-asset production progress to status and document stable IDs, maximum three calls, unknown results and review reuse.
- [x] Add Policy cases for exhausted revisions, conflicting observations and preserving passed assets. Update Bot prompt/Skill runtime-setup/README. Do not change the portable Skill main file or Pi components.
- [x] Run actual CLI and Pi fake-provider picture-book tests; verify send_files and existing validation remain unchanged.
- [x] Synchronize only source/guidance to the configured private picture-book Bot directory, preserving endpoint credentials, runtime settings and all existing workspace/database/assets. Train the copied policies locally, no provider calls.
- [x] Run Ruff, syntax, full Python suite and unchanged Pi suite. Record exact results and scope limits; no claims that subjective model quality is guaranteed.


## Verified outcome

- Failing-first model/CLI regressions cover budgets across renamed outputs, unknown outcomes, canonical review reuse, fixed criteria, corrupt or missing evidence, aliases, journal overwrite and explicit target/reference roles.
- Full Python suite: **1685 passed, 2 skipped**. Pi suite: **105 passed, 2 expected platform/dependency skips**. Focused final production/review/contract suite: **56 passed**. Ruff, 260-file syntax parse and diff checks passed.
- Real Pi + controlled HTTP test observes an exhausted asset as a normal error tool_result, performs no fourth generation, then continues review/build/draft attachment delivery. Model content is stubbed; no live paid model was invoked.
- Existing private Bot source/guidance synchronized with scoped backup; endpoints, workspace assets, legacy journals and databases untouched. Its 11-case BM25 policy was trained locally. Read-only status reports 36 untracked older request journals and does not infer their asset identity or reset them as new budget.
- Scope remains Bot-local. Pi packages/loop, DST schema, Event types and final QA validation are unchanged by this work. Subjective artistic quality still requires real review; reaching the cap does not approve a book.
