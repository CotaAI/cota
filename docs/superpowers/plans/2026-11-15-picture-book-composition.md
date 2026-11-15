# Picture-book composition without forced decoration

**Goal:** Restore transparent typography and support model-led composition with a small non-destructive preview command.

**Boundary:** Skill guidance describes visual goals without Cota tool names. The Bot renders proposals; the model judges aesthetics from real previews. No runtime change, forced decoration, new provider call or automated aesthetic score.

- [x] Reproduce the default-panel regression, restore background=null and padding=0, retain explicit decoration and structural/overflow checks, remove hard contrast rejection.
- [x] Add preview regressions for a selected page with incomplete other pages, candidate JSON, measured wrapping, text-region crops and unchanged formal book/evidence.
- [x] Implement bookbot/preview.py and preview --page N [--layout page.json], reusing PDF rendering and returning PNGs/metrics under .bookbot/previews without building or accepting the book.
- [x] Align Skill, Agent, Policy, README and CLI on natural negative space, palette, reading flow, subject avoidance and whole-page/detail inspection. Remove stale frozen-page/three-version text.
- [x] Run focused and full Python tests, Ruff/diff checks and visual QA; back up and sync definitions/code without touching endpoints or original production data.

## Observed baseline

The user rejected the mandatory ivory panels. Existing Skill already discourages default white boxes, but Agent and renderer contradict it. Building the complete book also updates formal outputs, making it unsuitable for isolated layout experiments.


## Verification

- Baseline typography suite: 3 failed / 5 passed, confirming the mandatory panel and hard contrast rejection. New preview suite: 4 failed before the module/CLI existed.
- Focused typography/preview: 12 passed; focused preview/render/contract/CLI coverage: 50 passed.
- Full Python suite: 1833 passed, 2 skipped, 28 dependency warnings in 363.86s. Log: `/tmp/cota-natural-layout-full-python.log`.
- Ruff and diff checks passed; 25 local links in edited Bot/Skill documentation resolve.
- Rendered and inspected real-artwork trial page and text crop without background panels; result paths recorded in `/tmp/cota-natural-preview-result.json`. Original production book remains unchanged; no live provider call or paid model evaluation was performed.
- Ten changed Bot files were backed up and synced to `cota_projects/picture-book`, preserving top_k=3 and endpoint file hashes. Backup: `/Users/mingguang.shao/work/cota_projects/.backups/cota-adaptation-20261115-150054`. Isolated load, Pi discovery, retrieval and Python syntax checks passed. The evaluation suite now has 14 cases / 16 turns; authored data was parsed, not paid-model evaluated.
- Preview provides rendering/measurement rather than aesthetic acceptance; the model must inspect the actual image. Existing explicit artistic backgrounds remain supported. No Cota/Pi runtime changes, global personal-Skill changes, database edits, commit or push.
