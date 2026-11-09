# Bot evaluation implementation plan

**Goal:** Deliver portable dialogue-based LLM evaluation with per-criterion evidence, reports, rejudging and comparisons.
**Architecture:** `cota/evaluation` owns authoring schema, judge, isolated runner and artifacts. It consumes existing Agent/Store/LLM interfaces without modifying runtime events. Training continues to read only direct policy YAML files.
**Tech stack:** Python, YAML, existing LLM adapter, Pi runtime, SQLite, JSON/Markdown artifacts.

Approved contract: `policy/eval/**/*.yml` contains `policies: [{name, steps}]`. Steps alternate user text and bot `{reply-review: [text, ...]}`. Only user text enters the tested conversation. Review entries are equal weight; future weights/skill-review unsupported. Each judgement is pass/fail/inconclusive with reason and event IDs. Infrastructure errors are distinct from business verdicts.

- [x] Add schema/judge tests: duplicate YAML keys, unsupported fields, invalid turn order, stable IDs/hashes, strict judge cardinality and evidence references, errors not passes.
- [x] Implement schema.py and judge.py using existing LLM.generate_chat; persist exact judge input and response, no fabricated reasoning.
- [x] Add runner tests: isolated cases/repetitions, original Bot untouched, rubric hidden, actual prior replies retained, partial failure artifacts, cleanup, timeout.
- [x] Implement runner.py: copy Bot excluding eval/history, replace Store with temporary SQLite; preserve trained resources; explicit environment limitations; record definition/model/judge identities without credentials.
- [x] Add artifact tests: versioned JSON and readable Markdown, per-criterion verdicts, changed-case/judge warnings, no-overwrite rejudge using saved evidence only.
- [x] Implement artifacts.py and CLI: cota eval; cota eval judge; cota eval compare. Nonzero exit for incomplete/failing evaluation.
- [x] Migrate weather scenarios to policy/eval, remove one-off runner and its obsolete tests, update integration coverage and user docs.
- [x] Run targeted and repository tests/static checks; update this plan with outcomes.

No legacy format compatibility, commits, or RSI implementation in this change. Personal machine tools and HTTP still have real external side effects; temporary directories are not a sandbox. Only direct conversations supported initially; group evaluation requires a separately designed inbound-message contract.


## Verification

- Evaluation contract/judge/isolation/report/rejudge/comparison tests: 27 passed.
- Targeted evaluation, real Pi + SQLite protocol, template, Policy/training regression: 134 passed (follow-up evaluator boundary tests also pass).
- Full repository run: 1,213 passed, 2 skipped; 24 local socket/process tests failed under sandbox restrictions, then all 24 passed with local network/process access.
- Static syntax scan: 231 first-party files; Ruff and diff whitespace checks passed.
- Real model smoke: activity_only and future_condition, followed by rejudge and compare; all execution/judge calls completed. Activity candidate grouping failed two criteria, future conditional plan passed five. Both original and rejudge produced the same criterion statuses. This tests infrastructure, not a claim of stable Bot accuracy or infallible judging.
- Live artifacts: `/private/var/folders/zg/zy3cpcf102qbyx_qbq8_dm3m0000gp/T/cota-evaluation-live-s87gb79z/`.
- No original configured Bot, credentials or conversation database modified. No commit made in the pre-existing dirty workspace.
