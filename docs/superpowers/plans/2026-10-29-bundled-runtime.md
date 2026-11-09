# Bundled Pi runtime implementation plan

**Goal:** A supported release wheel installs Cota, pinned Node and Pi using one pip command; normal startup does not use npm or download files.

**Architecture:** Maintainers prepare a verified platform runtime before wheel construction. A Hatch hook refuses an incomplete release wheel and embeds the prepared runtime with the correct platform tag. Runtime resolution prefers the package's own executable and worker; external Node remains a source-development/explicit override option.

**Tech stack:** Python stdlib build tooling, Hatchling, official Node 22.23.4 distributions, Pi Core 1.4.0 npm lockfile, native CI runners.

- [x] Add failing tests in `tests/test_pi_distribution.py` for bundled resolution without PATH, corrupt/missing bundle behavior, source fallback, platform tags/checksums and dependency completeness.
- [x] Implement `cota/runtime/pi_distribution.py` and adapt bridge/setup/config defaults. Keep wheel startup read-only and independent of npm; keep `pi_setup` for editable/source development.
- [x] Implement `scripts/bundle_runtime.py`, `scripts/node-runtime.json`, and `hatch_build.py`. Verify pinned SHA-256 before extracting; run npm ci with install scripts disabled in an isolated staging folder; retain licenses, lockfile and a manifest. Reject native npm artifacts unless platform compatibility has been explicitly handled.
- [x] Configure platform wheels and an sdist containing the build tools, but no generated binaries. Remove unused core ML dependencies and add the missing loguru dependency. Refresh the active uv lockfile.
- [x] Add a build-only CI workflow for four native targets and a clean-install smoke test that hides system Node/npm and disables network access while exercising a real Pi tool loop. No PyPI publishing in this change.
- [x] Build the local platform wheel, install it with pip into a fresh virtualenv (normal dependency resolution), run CLI and the offline Pi smoke test outside the repository, then run Python and Node regression tests and inspect package contents.
- [x] Update installation/release documentation and request read-only review before completion.

Support is conditional on successful native tests: Linux glibc >= 2.28, macOS >= 11; Windows/Alpine have no release wheels in this first matrix. Building from source remains a maintainer/developer workflow requiring build tools. Existing PyPI releases are unaffected until new artifacts are explicitly published.

## Verification results

- Native macOS ARM64 wheel built: `cota-1.1.1-py3-none-macosx_11_0_arm64.whl`, 53.53 MiB. Node executable mode and bundled npm modules/licenses inspected.
- Fresh Python 3.12 venv: normal `pip install <wheel>` against public PyPI succeeded; `pip check` passed.
- Outside the checkout: CLI and actual Pi model/tool loop passed with an empty PATH and Python/Node networking disabled. The model callback is deterministic; no live LLM request was made.
- Python regression suite: 485 passed, 7 skipped. Existing deprecation/coroutine cleanup warnings remain. Staged Pi Node suite: 6 passed.
- Unprepared release wheel build correctly rejected. Source archive inspected: build scripts and Node tests included, generated runtime/node_modules excluded. Source `pi_setup --check` and editable installation in a separate environment passed.
- Independent read-only review found no blockers.
- Other native platform jobs are configured but have not run here. No PyPI publication, commit or push performed.
