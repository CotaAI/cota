# Trainable Policy implementation

**Goal:** Make Cota Policy a pluggable, trainable business-guidance component, preserving the operator's ordered dialogue examples.

**Approved direction:** The user approved the preceding retrieval/model design and requested direct implementation under the name Policy. Train includes indexing, embeddings and compilation, not necessarily weight updates. Preserve the dirty feature/2.0 workspace; do not commit or restore unrelated files.

## Architecture

- `catalog.py`: existing annotation contract and rendering, independent of algorithms.
- `context.py`: bounded current conversation/tool evidence projection, excluding injected policy and private reasoning; no fabricated business stage.
- `base.py`: Policy lifecycle, matches, common validation/rendering, artifact versioning, atomic publication. Whole examples remain intact; optional model-selected Bot step is a focus label, not a destructive slice.
- `retrieval.py`: AllPolicy, BM25Policy (Chinese/Latin tokens), EmbeddingPolicy (named endpoint), RulePolicy (explicit literal rules compiled at train time).
- `model.py`: ModelPolicy, RetrievalModelPolicy and SearchModelPolicy (bounded literal grep/read over the policy corpus, never shell/filesystem or business tools).
- `factory.py`: registration plus explicit installed module:class plugins, strict per-class options, named model/embedding resources.
- `training.py`: `cota train --config BOT [--check]`, no Store/Pi startup. Models/indexes live in `models/policy.json`; schemas/hashes detect stale or damaged artifacts. AllPolicy needs no explicit training; other strategies require a matching artifact.
- Runtime calls async Policy.guidance with a fresh context before each main model request; existing Pi execution and context persistence remain. Common Trace records decisions, evidence, errors and omissions. Cache is bounded and keyed by complete projected context, never shared across sessions.

## Built-ins and contracts

`policy: {type, artifact, max_policies, max_chars, context_chars, timeout_seconds, options}`. Type defaults to all. Options are strategy-specific; unknown options fail. Embedding resources use `endpoints.yml embeddings`, chat resources use existing llms. Secrets never enter artifacts. JSON-only artifacts, no pickle. Explicit plugin code is developer-installed, not loaded from annotation data.

Policy methods: `async train(services) -> JSON state`, `load_state(state)`, `async select(context, services) -> Selection`; final `guidance` validates names/steps/evidence, enforces budgets and renders original examples. Training exposes the same extension contract to plugins. Model outputs are references, applicability assessments and concise reasons, not arbitrary instructions.

Rules match declared text fields and literal phrases, mark candidates only, and require no operator annotation format changes. SearchModelPolicy exposes only bounded `grep_policies` and `read_policy`; retrieval text and tool outputs remain data. Missing/stale artifacts fail with a train instruction. Runtime model/provider errors fall back to candidates with explicit Trace diagnostics; cancellation/checkpoint failures are not swallowed.

## Tasks

- [x] Write failing lifecycle/context/retrieval/plugin/CLI tests.
- [x] Implement common contracts, deterministic training artifacts, BM25/rule/all strategies.
- [x] Implement embedding provider and model/search/composed strategies with response/evidence validation and bounded work.
- [x] Wire Agent/config/CLI/annotation budgets and async Pi prepare; migrate tests to the Policy runtime contract.
- [x] Add real Pi integration tests and CLI offline training smoke; validate no example-to-evidence contamination.
- [x] Update documentation and weather example; run focused and full regression and inspect diff.

## Validation

Use `.venv/bin/python -m pytest`. External model/embedding boundaries are deterministic in tests; real Pi tool loop and Store remain exercised. Test invalid outputs, stale artifacts, cancellation, empty results, user task changes, same-session cache correctness and cross-session isolation. No claim of real-model quality improvement without evaluation.

## Results

- Initial contract tests: 6 expected failures before the API existed.
- Focused regression: 88 passed; expanded new Policy suite: 30 passed.
- Final full regression: 651 passed, 7 skipped, 274 warnings; `/tmp/cota-policy-final-full.log`.
- Fixed two integration issues exposed by tests: JSON-native decision evidence and CLI logging argument.
- Fixed retrieval contamination from Skill reads/tool paths and reserved context space for the latest user request under large tool outputs.
- Validated documented Policy YAML/configuration and custom-class example syntax; `git diff --check` passed.
- Built wheel/sdist offline; verified packaged Policy sources and weather template match current files.
- Installed-wheel smoke passed CLI training/check, all three Bot templates and real Pi tool loop with network disabled and without system Node/npm; `/tmp/cota-trainable-smoke.log`.
- Training artifacts, builds and installation smoke files are in `/tmp`; no commits or publication.
- Model applicability remains an assessment, not a verified business fact. Whole examples are retained; focus steps do not crop conditions. No real-provider model-quality benchmark claimed.
