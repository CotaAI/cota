# Pi Tool Environments Implementation Plan

> Execute inline against the user's existing feature/2.0 workspace; preserve unrelated edits.

**Goal:** Reuse Pi's four low-level tools with explicit Cota execution environments.
**Architecture:** Immutable Python environment binding, Pi native tools assembled in Node,
acknowledged authorization and outcomes through the existing bridge/Event/Store lifecycle.
**Tech Stack:** Python, Node ESM, pinned Pi 1.4.0, pytest, node:test.

- [x] Add failing configuration/runtime tests in tests/test_execution_environment.py for
  explicit host workspace, default none, unsupported/invalid modes, real write/edit/read/bash,
  no-Skill operation, result provenance, persistence and revocation.
  Run `.venv/bin/pytest tests/test_execution_environment.py -q` and confirm missing behavior.
- [x] Add frozen ExecutionEnvironment in cota/executor/environment.py; validate in config.py,
  bind from agent.py and snapshot in pi_runtime.py. Core names reserved, extensions retain policy.
- [x] Split discovery in skills.mjs from tools.mjs assembly using official ToolDefinition factories.
  Bind native operations to the environment, preserve Pi guidelines, authorize native calls and
  acknowledge native results. Integrate engine.mjs and update direct worker tests to the split API.
- [x] Record compact native results and environment run metadata; reuse events/DST restoration.
  Add tests for failed checkpoints and native permission checks with model tools actually invoked.
- [x] Propagate worker cancellation through Pi AbortSignal, verify spawned command termination.
  Run Node tests and focused pytest suites, fix regressions before broad validation.
- [x] Document environment contract and examples; keep default templates none and opt in host
  explicitly. Update affected module/skill/debug docs. Run full Python and Node suites and review diff.

## Verification

- Real Pi factories: write/edit/read/bash, Skill and ordinary-file provenance, image output,
  nonzero exit, bounded timeout and bridge cancellation passed.
- Full Python suite: 1,150 passed, 25 failed, 1 skipped in the restricted sandbox.
  24 failures were localhost/ps permission restrictions; one direct `_prepare` unit fixture
  needed the new nativeTools protocol field. After that fixture correction, all 25 passed
  when rerun with local network/process inspection permissions. Additional environment tests
  added after collection also pass in the focused run.
- All 44 Node tests passed; source syntax/Ruff checks and git diff whitespace checks passed.
- No real provider requests, remote backend deployment or release publication performed.
