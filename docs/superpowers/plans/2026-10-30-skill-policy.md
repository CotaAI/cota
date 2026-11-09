# Skill Policy Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement and review the isolated policy/annotation task. Root integrates runtime and configuration in the existing dirty workspace without reverting prior work.

**Goal:** Define business capabilities by Skill, retain execution evidence in Trace, derive explicit Policy cases from skill-name annotations, and apply Policy during real Pi model requests.

**Architecture:** Replace DPL with a strict versioned PolicyCatalog. Selection cases apply to the available Pi Skill catalog; execution cases apply to successfully read Skills still represented in model context. Annotations remain separate evidence-backed judgments; explicit export creates reusable Policy files, never silently promotes user traces into instructions.

**Tech Stack:** Python, PyYAML, Pi Agent Core / Coding Agent (existing pinned TypeScript dependencies), pytest, Node tests.

## Task 1 — Policy contract and annotations
- [x] Add failing tests in tests/test_skill_policy.py and tests/test_skill_annotations.py for strict cases, multiple Skills, stage filtering, budgets, malformed/unknown fields, annotation evidence, round trips and explicit export.
- [x] Create cota/policy/ with PolicyCatalog.load(path, max_cases=8, max_chars=12000), validate_skills(names), guidance(available_skills, read_skills) returning text and case identities; versioned YAML {schema_version: 1, cases: [...]}. Each case has id, stage (selection/execution), skills, when, guidance, optional provenance. Skills is an ordered list supporting combinations; when is an explicit condition for the model, not claimed semantic retrieval.
- [x] Add skill_annotation events, DST.annotate_skill and Trace.skill_annotations. Validate actual evidence IDs, run linkage and skill names; allow wrong/missing selection annotations without fabricating reads. Add explicit export_policy(dst, annotation_ids, case_id, stage, when, guidance) returning a versioned document with provenance. No automatic runtime learning from traces.
- [x] Run focused tests and independent spec/quality review.

## Task 2 — Runtime, configuration, cleanup
- [x] Add regression tests proving selection guidance before read, execution guidance on the next model request after read, multiple skills, resumed reads, rejection of obsolete configuration, and actual tool result visibility.
- [x] Agent loads singular policy configuration {max_cases, max_chars} and policy/*.yml; no policies/DPL or actions. Validate top-level keys, core nested contracts and old prompt placeholders early. Keep Agent public name to avoid unnecessary API churn.
- [x] Runtime calls PolicyCatalog on every prepare, using current Pi discovery and successful read call IDs in the retained context. Include selected cases in context_prepared; fail explicitly on invalid policy skill references. No active_skill routing.
- [x] Remove cota/dpl and unused DST thought/RAG/policy helpers, old action-specific knowledge routing and parser helper. Rename executor/skills to executor/tool_servers and create_skill_tools to create_tools; remove obsolete factory aliases where unused.
- [x] Migrate old tests to the new behavior, removing tests solely for deleted DPL algorithms.

## Task 3 — Templates, docs and validation
- [x] Migrate weather and pet to Skill-based cases; add a pet-care Skill so the example has an actual business identity. Preserve hello as plain chat.
- [x] Replace current Action/DPL configuration docs and stale tutorials with supported examples; update architecture and naming references, leaving historical plan documents intact.
- [x] Run full Python suite, real Pi Node tests and template integration tests; inspect diff hygiene. Report mock-model versus real-provider boundaries accurately.

## Completion evidence

- Policy guidance is recomputed on every Pi prepare. Execution cases precede selection cases; individually oversized cases fail loading and budget omissions are recorded explicitly.
- Successful context reads use exact durable `cotaResultEventId` references; IDs reused across runs cannot activate historical execution policies. Compression re-evaluates policy before final size validation.
- Skill annotations require an applicable Pi discovery snapshot, real evidence and target-run linkage; explicit manual export is exercised through YAML publication, Bot reload and the real Pi loop.
- Independent spec and code-quality reviews approved after fixing budget starvation, unknown annotation names, call-ID ambiguity and premature compression size validation.
- Full suite: **598 passed, 7 skipped, 250 existing warnings**, 75.51 seconds. Log: `/tmp/cota-skill-policy-verified.log`. The initial sandbox run had four local port/process permission failures; the permitted full rerun passed.
- Source and bundled Node runtime tests: **15 passed** each. Bundle: `.build/pi-runtime-skill-policy`.
- Built wheel and sdist in `/tmp/cota-skill-policy-dist`; inspected package source matches and absence of removed modules.
- Installed wheel smoke: CLI, three Bot templates and real Pi loop pass with system Node/npm and network unavailable. Log: `/tmp/cota-skill-policy-smoke.log`.
- Model/service responses are controlled in automated tests; no claim of real-provider quality evaluation. Policy remains conditional model guidance, not deterministic routing or automatic RSI. Annotation APIs/export are available; no annotation UI is claimed.
- Documentation relative links and example syntax validated; mdbook was unavailable. `git diff --check` passed. No commit, push or publication performed.
