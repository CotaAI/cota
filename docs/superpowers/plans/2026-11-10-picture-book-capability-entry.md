# Picture-book capability discovery implementation plan

**Goal:** Keep capability purposes in agent.yml, invocation instructions in the existing Skill environment guide and CLI help, and real paths in runtime metadata.

**Approved boundary:** The user confirmed that Skills or companion entries supply invocation methods and the runtime supplies actual locations. No new instruction file, Cota tool, model service, or endpoint schema is needed.

**Architecture:** Cota passes its Python executable to the Pi worker. The existing machine environment prompt advertises the absolute Bot directory, working directory and interpreter. The picture-book Skill's existing runtime-setup.md describes its optional companion CLI relative to that advertised Bot directory, using quoted absolute paths. Generic SKILL.md remains unchanged; endpoint credentials remain private.

**Files:** cota/runtime/pi_runtime.py; cota/runtime/pi/tools.mjs; bots/picture-book/agent.yml; bots/picture-book/skills/creating-childrens-picture-books/references/runtime-setup.md; bots/picture-book/scripts/book.py; bots/picture-book/README.md; docs/src/concepts/tool-adapters.md; tests/test_picture_book_bot.py; tests/test_context_optimization.py; cota/runtime/pi/worker.test.mjs.

- [x] Add a failing bridge assertion for the real Python executable and a failing native prompt assertion for Bot/interpreter locations.
- [x] Pass sys.executable through the existing worker options; advertise actual locations only for machine execution. Leave Pi factories and execution semantics intact.
- [x] Move Bot invocation details from agent.yml into the existing Skill environment guide and align CLI help/README. Keep model IDs and credentials in endpoints.yml.
- [x] Exercise the documented absolute CLI from a copied Bot with spaces in its path and from a nested project directory, without model requests.
- [x] Update the controlled real-Pi picture-book test to read the environment guide, inspect runtime paths, and run the companion from a nested directory.
- [x] Run focused Python/Node suites, lint and diff checks. Sync only the modified Bot instruction/help files into the private deployment, preserving endpoints, indexes, books and database. Record results here.

Verification:

- RED: two Python regressions failed for absent interpreter metadata and absent companion guidance; native Node test failed for absent Bot location. Logs: /tmp/cota-capability-red-python.log and /tmp/cota-capability-red-node.log.
- GREEN: both Python regressions and the native metadata test passed. The copied Bot path contains spaces; real Pi reads the guide and invokes status from the nested project directory, then resumes through SQLite.
- Focused Python suite: 156 passed, 1 skipped, 3 dependency deprecation warnings (/tmp/cota-capability-python.log).
- Pi Node suite: 52 passed, 2 platform skips (/tmp/cota-capability-node.log).
- Static check: 262 first-party sources parse; Ruff passes (/tmp/cota-capability-static.log). git diff --check passes.
- Generic SKILL.md is byte-identical to the supplied original. SOURCE.md records the optional runtime-setup.md adaptation.
- Five private instruction/help files synced atomically. Existing endpoint configuration and trained Policy index hashes unchanged. Books and database were not written.
- Private doctor invoked from the existing antibody-squad-v1 project directory with absolute interpreter/script paths: ready=true, no network/model requests.

No commit/push or paid model inference is part of this change.
