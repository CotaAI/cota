# Picture-book Bot Implementation Plan

2026-11-10: delivery is superseded by the unified attachment implementation. The Bot-local serve.py and token publisher were removed; historical verification below describes the original implementation only. See [attachments plan](2026-11-10-attachments.md).

2026-11-10 portability follow-up (approved): keep the original Skill independent
of Cota, remove its Cota-only runtime document/link, and keep concise invocation
guidance in agent.yml. Multimodal configuration remains in endpoints.yml; automatic
model-purpose injection and a model knowledge resource are deferred.

- [x] Replace the real Pi integration's deleted-file read with script help and
  first reproduce missing layout guidance (`image_box` / `text_elements`).
- [x] Restore SKILL.md, delete references/cota-runtime.md, update agent.yml,
  and expose detailed command/layout contracts through book.py --help.
- [x] Update README/SOURCE, validate the copied Bot and its original Skill tests,
  and run syntax/Ruff plus whitespace/reference checks.

Follow-up verification: the changed Pi integration initially failed because build
help lacked the layout contract, then passed with actual Bash help output and
SQLite resume. The focused Bot/template/attachment/Cmdline/Skill regression run
passed 74 tests (three existing websockets deprecation warnings); log:
`/tmp/cota-picture-book-portability-tests.log`. Syntax/Ruff passed for 258 source
files; log: `/tmp/cota-picture-book-portability-static.log`. SKILL.md is byte-identical
to the original local source, all nine help entry points work without model calls,
and template enumeration excludes the removed runtime document. No core runtime,
provider configuration, model routing or prompt knowledge injection changes.

> **For agentic workers:** Use inline execution with verification after each component; do not change Pi or introduce a second execution framework.

**Goal:** Ship a portable picture-book Bot with configurable image/vision services, reproducible PDF production and Web download delivery.

**Architecture:** Bot-local scripts and optional Web launcher reuse Pi and Cota's public app. Only generic safe text-link rendering changes the shared chat UI. Optional publishing assets are outside core Store and never included in templates.

**Tech Stack:** Existing OpenAI SDK/PyYAML; optional Pillow, ReportLab and pypdf; installed Poppler; Sanic; pytest/Node tests.

## Tasks

- [x] Write failing tests in `tests/test_picture_book_bot.py` for template portability, multimodal protocol, generation reuse, rendering, and publication. Run before adding scripts.
- [x] Copy the complete Skill into `bots/picture-book/skills/creating-childrens-picture-books`; document provenance and Cota runtime instructions separately.
- [x] Add `agent.yml`, `endpoints.yml`, optional `requirements.txt`, Policy and held-out eval files. Keep all credentials empty.
- [x] Implement small modules under `bots/picture-book/bookbot` and CLI `scripts/book.py`: common paths/config/JSON operations, multimodal requests, PDF layout/rendering and file publication. Protocols are tested through HTTPX MockTransport, no real keys.
- [x] Add Bot-local `serve.py` to compose the existing optional chat app and download route; test real HTTP with existing `running_app` fixture. Publishing snapshots selected files, expires links and rejects path escape/symlinks.
- [x] Add tested safe link rendering to `cota/webapp/static/app.js` with DOM APIs; preserve literal text and no arbitrary HTML.
- [x] Extend existing template/init checks to include both weather and picture-book, including references/scripts/assets in package enumeration.
- [x] Add a real Pi integration test for Skill/read/write/Bash, SQLite replay and final downloadable output with controlled external responses.
- [x] Run focused tests, static checks and complete regressions; visually inspect a generated Chinese sample PDF via page renders. Record provider/model quality as untested until credentials are configured.
- [x] Update Bot catalogue and relevant docs with precise shell/Web/eval commands and personal deployment/download-link limitations.

## Verification evidence

- Full shared regression: 1438 Python passed, 2 skipped; branch coverage 87.46%; 83 JavaScript passed, 2 skipped. Log: `/tmp/cota-picture-book-checks.log`.
- Final Bot/template regression after additional review fixes: 44 passed. Log: `/tmp/cota-picture-book-focused.log`. Static syntax and Ruff passed; `git diff --check` clean.
- Includes actual Pi child process + native Bash + localhost Images generations/edits + vision HTTP + PDF render + draft publication; no paid provider requests.
- Independent review found YAML exception leakage and stale deliverable substitution. Both reproduced with failing tests, fixed and reviewed again. Publication validation binds all deliverable paths and hashes to the current render.
- Eight-face Chinese PDF manually inspected from rendered overview; embedded Chinese TrueType verified with pdffonts, structural blank faces checked. Assets: `/tmp/cota-picture-book-visual` (test fixture, not a finished book).
- Full Skill validator smoke tests and print-profile regressions passed; copied fixtures updated to current language-review contract.
- Portable template enumeration: 50 files / 179636 bytes at verification; no credentials, workspace, .cota or caches included.
- Browser access to the localhost preview was declined. No UI workaround attempted; interactive browser acceptance remains unverified. Real HTTP/WebSocket/download tests and safe link parser tests passed.
- Real-model image quality, service-specific compatibility and physical print proof remain for user-configured verification. No commit/push or release requested for this change.
