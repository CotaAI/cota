# Policy result Implementation Plan

**Goal:** Add optional natural-language `result` observations to ordered Policy examples without treating them as real execution evidence.

**Architecture:** Extend the shared Policy validator and renderer, reused by annotation files, Store annotations and runtime guidance. Keep results inside complete examples; Pi continues to judge applicability using actual tool results. No result enum, automatic branch router, inferred Skill completion or new event type.

**Tech Stack:** Python, YAML, pytest, existing Pi Agent Core bridge.

The user approved this design and requested implementation. Work in the current feature/2.0 workspace; preserve the existing uncommitted migration. No commits or worktree migration needed for this incremental change.

## Contract and implementation

- [x] Add failing tests in `tests/test_skill_policy.py` for nonempty text results, repeated results, complete branch rendering, round trips and invalid values. `thought → result → reply` must target reply, not result; trailing observations leave thought as continuation.
- [x] Extend `cota/policy/__init__.py`: accept `result` alongside thought/reply; find thought targets only among skills/reply; render results as `Result（示例结果条件）`. Explain that missing/failed real results cannot be replaced by example results, and read is not execution.
- [x] Update `cota/annotation_files.py` and `cota/annotation_cli.py` instructions. Preserve authored results through imports, revisions and re-exports, but do not infer results from historical reads or tool outputs.
- [x] Test handwritten and source-linked import/export in `tests/test_annotation_worksheet.py` and `tests/test_annotation_cli.py`; test real Pi requests, actual tool failure and resume in `tests/test_skill_policy_runtime.py`. Confirm example observations never become actual messages/tool results.
- [x] Update weather Bot examples for successful results, invalid data, missing city and service failure; update `tests/integration/test_example_bots.py` to inspect model guidance and unchanged evidence, including reviewed results loaded from Store.
- [x] Update current Policy docs and other format descriptions. Document splitting multiple Skill/result sequences when attribution matters, optional results, conditional branch examples and real evidence boundaries.
- [x] Run focused Policy/annotation/Pi/example tests, then the full suite. Check changed files and whitespace. Record results below.

## Validation commands

```bash
.venv/bin/python -m pytest -q tests/test_skill_policy.py tests/test_annotation_worksheet.py tests/test_annotation_cli.py tests/test_conversation_annotations.py tests/test_skill_policy_runtime.py tests/integration/test_example_bots.py
.venv/bin/python -m pytest -q
git diff --check
```

Deterministic model responses verify injection and evidence separation, not real-model branch selection quality.

## Verification results

- Red phase: 7 intended failures because result was not accepted by the shared validator.
- Focused regression: 74 passed.
- Final full regression: 621 passed, 7 skipped, 255 existing warnings (74.48s); `/tmp/cota-result-full.log`.
- Validated all 5 documented Policy YAML blocks and both shipped Policy catalogs; all 6 weather examples fit the configured budget.
- `git diff --check` passed.
- No model-quality claim, commit or publication.
