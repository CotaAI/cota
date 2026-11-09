# Conversation workflow annotation

Goal: annotators read a conversation, select a continuous message span, edit ordered Skill steps in plain language and export Policy without managing run IDs, evidence IDs or Policy syntax.

Design: an editable YAML conversation worksheet backed by the existing Store; a pure projection and validation module; append-only flow_annotation events; deterministic Policy compilation. Observed reads and tool evidence are displayed separately from the expected process. Repeated Skill steps are meaningful and preserved. Missing and unnecessary capabilities can be labeled without fabricating reads. Revisions supersede earlier interpretations without editing facts. Policy publication remains an explicit downloaded file + Agent reload.

Implementation in this session (user authorized optimization):
- [x] Add failing tests for conversation projection, multi-turn selection, ordered repeated steps, automatic evidence, validation, supersession, persistence and Policy compilation.
- [x] Implement cota/annotations.py and integrate flow_annotation into Event/Trace; keep low-level technical annotation for integrations.
- [x] Add AnnotationService with Store locking/revision checks and policy export, tested against MemoryStore/SQLStore.
- [x] Add cota annotate export/import CLI and a commented YAML worksheet: generated conversation and Skill catalog; numbered message ranges; named cases with ordered skill/do or skill/avoid steps; optional example reply. Import validates the unchanged source, applies a whole batch atomically and generates a Policy file. No model or Pi dependency at annotation time.
- [x] Test generated Policy through actual Pi runtime with controlled model responses; test CLI export/edit/import and Policy file loading.
- [x] Update primary docs from technical API-first to conversation-first; run focused tests, full suite and packaging asset check.

Scope: existing persisted conversations with Pi discovery evidence. No synthetic Skill catalog, semantic auto-labeling, automatic online publication, annotation workforce assignment or hosted multiuser authentication. A memory-only Bot can use the worksheet functions with its live Store; standalone CLI requires persistent SQL Store. User explicitly selected files over browser UI; no UI implementation.

Verification completed:
- Tests first: missing annotation module, worksheet module, CLI parser; then regression failures for repeated run projection and pending/blocked tool calls.
- Full suite: 631 passed, 7 skipped (existing warnings), /tmp/cota-annotation-verified.log.
- End-to-end actual Pi loop with controlled model responses verifies generated selection/execution guidance in model requests.
- Offline wheel/sdist build passed; wheel source matches current modules. Installed wheel CLI export/edit/import and Policy loading passed outside repository (/tmp/cota-annotation-installed-smoke.log).
- File import validates all cases before one Store save; SQL and memory roundtrip/revision conflicts tested.
- User chose files, so no browser UI was added.
