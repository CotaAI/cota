# Repository audit and regression coverage

**Goal:** Review every first-party executable source file, remove verified obsolete code, repair demonstrated defects, and leave reproducible checks for future AI-assisted development.

**Architecture:** Preserve Pi Core + Tool + Event/Trace, DST event replay and Store persistence, Application scheduling, transport adapters and optional Web app boundaries. No old-runtime compatibility, provider calls, deployment changes or broad style rewrite. Current dirty/untracked 2.0 work is the baseline and must not be reverted.

**Inventory:** Enumerate Python, JavaScript/ES modules and shell under the repository, excluding virtual environments, downloaded/vendor runtimes, generated workspaces/build artifacts and .git. Syntax-check all first-party code; review production files by four responsibility groups. Review tests by behavioral coverage and static diagnostics. Record per-file disposition in the audit artifact.

## Tasks

- [x] Inventory and syntax checks: Python AST, Node --check, bash -n; Ruff F/E9 diagnostics, full pytest with branch coverage. Inspect all reported diagnostics, especially exports and plugin registrations, before removing imports.
- [x] Core state/runtime audit: Agent/Processor, DST/Store/events/snapshots, group/participation, Pi bridge/context/distribution and JavaScript worker. Confirm concrete correctness gaps with deterministic tests.
- [x] Application/Channel audit: server/application, Channel lifecycle/delivery, HTTP/WS isolation, optional Web app, debug. Confirm old frontend orphan references before deletion; add regressions for replay backpressure, cancellable console lifecycle and per-Bot app state.
- [x] Policy/tool audit: annotations/training/inference, MCP session management, scheduler ownership/concurrency/shutdown, subprocess tool export and HTTP URL checks. Implement reproduced defects with focused tests first, keeping trusted deployment/device MCP access distinct from public HTTP URL policy.
- [x] LLM/config/utility/packaging audit: fix Custom HTTP cleanup and response normalization; verify knowledge works with real LLM adapter signatures, remove duplicate or unreferenced old helpers, keep SQL dialect/runtime resource entry points.
- [x] Test infrastructure: replace false-positive/unawaited legacy model tests, explicit fixture cleanup, strict unawaited/unraisable warnings, development lint/coverage dependencies, documented single verification entry point and CI. Keep genuine tests for behavior/edge cases rather than assertions matching implementation.
- [x] Consolidate independent findings and review changes, run full checks after fixes, collect final branch coverage and per-file audit/test map. Document remaining live-provider/MySQL/platform validation limits without claiming exhaustive proof of absence of bugs. No commit requested.

**Final verification:** 227 source files pass syntax/Ruff; 1155 Python tests pass, 1 intentional skip; 42 Node tests pass. Combined Python statement/branch coverage: 85.74% (baseline 76.29%). See `docs/audits/2026-11-05-code-audit.md` and `tests/README.md`.
