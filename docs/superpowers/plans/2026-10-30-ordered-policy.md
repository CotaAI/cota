# Ordered dialogue Policy implementation

Goal: implement the approved policies/name/steps schema, with user text and ordered bot lists containing thought, skills and reply. No required transcript, when, message ranges, stage or generated case schema.

Architecture: one strict public contract used by handwritten files, transcript-derived edits and runtime. Preserve complete example order and expose thought-to-next-behavior attribution in Trace. Provide bounded complete examples at every model request; successful retained reads prioritize related examples, never prove business completion. No deterministic semantic matching or invented execution state. Annotator thought is business instruction, never synthesized model reasoning.

Tasks (executed in this session under user's approved design):
- [x] Write failing schema/compiler/runtime tests for repeated thoughts, ordering, reply-only and thought-only policies, duplicate-key rejection, budgets and fact/example separation.
- [x] Replace PolicyCatalog contract; migrate runtime guidance and context_prepared records, config budget names and bundled Bot policies.
- [x] Replace range-based flow annotations with policy_annotation snapshots; keep source references in a separate sidecar. Preserve append-only revisions and source validation.
- [x] Update worksheet and CLI: direct authoring requires no Store; transcript export contains messages/replies without turning observed reads into prescribed Skill use; linked import saves edits and source evidence.
- [x] Migrate obsolete tests and integration fixtures; validate thought before and after actual Pi tool results, resume and compaction.
- [x] Rewrite docs and templates, verify full suite and installed wheel CLI using existing unchanged runtime bundle.

Validation: test first for changed behavior; full Python regression; installed offline CLI smoke; exact wheel source comparison; git diff --check. Preserve unrelated workspace changes; no commit or publication requested.

Verification completed:
- Full regression: 610 passed, 7 skipped, existing warnings; /tmp/cota-ordered-verified.log.
- Real Pi loop with controlled model/tool responses verifies ordered thought guidance before reads, after tool failure, through ask_user resume and after context compaction.
- Bundled weather/pet tests cover policy file loading, reviewed annotation persistence, Agent reload and Trace thought attribution.
- Offline wheel/sdist built; installed CLI handwritten and source-linked export/edit/import passed.
- Installed templates and actual Pi loop passed without network or system Node/npm; /tmp/cota-ordered-runtime-smoke.log.
- Wheel contents match edited Policy/runtime/annotation modules and Bot configurations. Documentation examples parse; git diff --check passes.
- Removed obsolete case/stage/when/guidance exporter and message-range flow annotation contract; preserved independent low-level skill/tool annotations. No production-model decision quality claim.
