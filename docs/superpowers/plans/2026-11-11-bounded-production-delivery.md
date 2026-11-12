# Bounded production and delivery implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development with explicit file ownership and failing-first tests. Preserve live Bot artifacts and credentials. No paid model calls, no new Event types, no Pi package edits.

**Goal:** Close the audited 100-decision run's page-edit/rebuild/review loophole and prevent late attachment failure while preserving a useful final response.

**Architecture:** Pi's public request/turn hooks remain the only execution loop. Cota's Node adapter exposes remaining decisions and reserves a final no-tool response; Python records normal outcomes. Cota FileStorage owns actual file limits and precise preflight errors, surfaced through the existing send_files definition. The portable picture-book package owns visual page revisions, deterministic layout/export and version-bound review evidence.

**Tech Stack:** Existing Python/HTTPX/Pillow/ReportLab/Poppler, Pi 1.4 public factories/hooks, pytest and Node test runner.

## Ownership and interfaces

1. Runtime worker: cota/runtime/pi/engine.mjs and new budget tests only. Request guidance includes total/used/remaining, warns before exhaustion, and enters final no-tool wrap-up within the original maximum. Default reserve is up to two calls for meaningful budgets (no reserve for maxIterations<10); optional explicit options.wrapUpIterations supports tests/callers. No additional loop or Pi source changes. Outcome hasFinalReply prevents Python's generic limit message replacing/duplicating a committed summary. Forced wrap-up remains status=limited, normal completion before it remains completed.
2. Attachment worker: cota/files.py, cota/runtime/pi/files.mjs, focused tests only. FileStorage.capabilities() returns max_file_bytes and max_attachments. Typed export validation carries reason, relative file, actual_bytes and max_file_bytes; no partial imports. Factory accepts these supplied limits and advertises them. Main wires options.fileLimits and Python error details.
3. Rendering worker: bots/picture-book/bookbot/layout.py, new bookbot/render_state.py and focused rendering tests only. build(root, project, max_file_bytes=20*1024*1024) adds explicit image_fit cover/contain and efficient print-quality image encoding preserving original assets/vector text. Distinguish visual page fingerprints from validation/printing metadata; metadata-only updates do not rerender/reset visual QA. Per-page successful versions allow one baseline plus two revisions, including local edits. Accepted current-version structured reviews freeze a page. Identical or repaired output does not spend another revision. Preflight before replacing outputs; changed source invalidates affected evidence, never auto-approves QA. Export size checked before artifact commit; return pending/changed pages and delivery size metadata. Expose render_status(project) for CLI.
4. Main: CLI, model-review assessment, policies/docs, integration tests and private Bot synchronization. CLI exposes remaining page progress and export preflight, produces compact machine-friendly summaries by default with full evidence retained. Review saves validated structured checks/verdict (required violations vs advice vs uncertainty); free-text/invalid structure remains uncertain without another paid call. Existing canonical cached evidence is preserved. No automatic retrospective approval.

## Execution tasks

- [x] Capture RED for warning/reserved final response/side-effect blocking and verify native tool declarations plus both transports remain correct.
- [x] Capture RED for precise too-large/missing/nonregular file errors, atomic multi-file rejection and advertised runtime limits.
- [x] Capture RED for cover/contain geometry, print-efficient PDF, metadata-only no-render/no-QA reset, per-page changed versions and accepted-page freeze, damaged output repair and oversized export preserving prior artifacts.
- [x] Implement within ownership; inspect each worker's diff and exact verification evidence before integration.
- [x] Wire budget completion and attachment limits in pi_runtime.py; wire CLI build/deliverables/status, review assessment and concise stdout with saved report paths.
- [x] Update Bot agent.yml, existing Skill runtime-setup, policies and examples: no ad-hoc Pillow loops, no head/tail pipelines masking status, fixed required/advisory criteria, preserve passed pages, size preflight before final QA.
- [x] Reproduce the 20 MiB + 85085-byte case offline and verify genuine Pi tool-error -> useful closing response within max calls. No provider spend or live artwork mutation.
- [x] Run targeted/full Python, Node and static checks; synchronize only code/guidance/index to the configured private Bot, preserving endpoint configuration, databases and existing works. Report actual validation and remaining limits.


## Verification and handoff

- Full Python suite: **1738 passed, 2 skipped** (313.03s), `/tmp/cota-bounded-full-python.log`. After the final physical-proof invalidation correction, all **126 picture-book regressions passed** (18.95s), `/tmp/cota-book-final-integration.log`; the new printing-profile regression was first observed RED. This last correction leaves visual QA/budgets intact while clearing only an obsolete physical proof.
- Pi Node suite: **131 passed, 2 platform skips**, `/tmp/cota-bounded-full-node.log`. A genuine spawned-worker test exposed and fixed the dropped `hasFinalReply` result flag; Python-to-Pi integration confirms eight work calls and one final reply within a ten-decision budget, with Store replay equality.
- Ruff, compileall and `git diff --check` passed. CLI/template/runtime integration: 34 passed. The two added portable helpers are included by `template_files`.
- Isolated copy of the existing 12-face book: PDF **21,056,605 -> 3,223,886 bytes**, identical extracted text and original image hashes, all four delivery artifacts successfully imported into a temporary FileStorage. Overview visually inspected for layout preservation. This validates export/delivery, not renewed semantic/medical/visual acceptance of the book. `/tmp/cota-offline-export-check.log` records the protected temporary project.
- Synchronized nine changed/new template source/guidance files to `/Users/mingguang.shao/work/cota_projects/picture-book`, with protected temporary source backups. Credentials and existing live manifest/PDF hashes verified unchanged; no database or artwork writes. Local BM25 rebuilt and `cota train --check` confirms **13 cases**. No paid model calls.
- No new Event type, Pi package modification, public YAML setting or secondary execution loop. Restart Shell to load Python/Node changes; old review prose remains uncertainty and is never retroactively marked passed. No commit/push performed for this task.
