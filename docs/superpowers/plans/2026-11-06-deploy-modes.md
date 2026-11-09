# Deployment Modes Implementation Plan

> **For agentic workers:** Execute inline with superpowers:executing-plans; preserve existing workspace changes.

**Goal:** Expose `deploy: personal | service`, independently of machine location, and bind native tools accordingly.

**Architecture:** Default to service with no business filesystem. Personal defaults to a machine environment rooted at Bot `files/`; explicit `none` remains possible. Rename the old host backend to machine. Service cannot bind the unrestricted machine backend; no sandbox or remote client backend is invented. Preserve Pi factories and existing transport-level service safeguards. Freeze and record deploy alongside the execution environment and reject changes before native calls.

**Tech Stack:** Python config/Agent/DST, Node Pi adapter, pytest and node:test.

- [x] Add failing tests in `tests/test_deploy.py`: accepted modes, rejected legacy names, personal default workspace, service rejection of machine in config and programmatic use, runtime revocation, metadata replay. Add Node bridge mode rejection test.
- [x] Implement `ExecutionEnvironment.for_deployment(deploy, config, base_path=...)` and `validate_deployment(deploy)`, validate top-level deploy, wire Agent defaults/load and Pi runtime/worker binding. `personal + omitted environment` resolves `machine/files`; `service + machine` raises before execution.
- [x] Update run metadata to include deploy and validate its relationship with the environment without resolving historical paths. Keep event schema unchanged.
- [x] Migrate machine fixtures and native integration tests; update examples to explicit service, configuration and deployment docs. Old host/local/remote names fail rather than aliasing.
- [x] Run targeted Python/Node tests, static checks, full relevant regression suite. Record results; no commits or unrelated changes.

Commands: `.venv/bin/pytest tests/test_deploy.py -q` (red then green); `.venv/bin/pytest tests/test_execution_environment.py tests/test_run_metadata.py tests/test_pi_skills.py -q`; `node --test cota/runtime/pi/worker.test.mjs`; `.venv/bin/python scripts/check.py --static-only`; `.venv/bin/pytest -q`.


## Verification

- Red phase: new Python contract tests failed on unsupported deploy/Agent argument and missing machine backend; new Node boundary test failed on the old environment contract.
- Targeted Python: 76 passed, 1 skipped (fd unavailable in the initial environment).
- Full Python with the existing isolated Pi fd cache: **1220 passed, 1 skipped**, 20 existing websockets deprecation warnings; exit 0. Log: `/tmp/cota-deploy-pytest.log`. Local socket/process tests ran with sandbox escalation.
- Full Node worker/debug/web regression: **52 passed, 1 skipped** (Windows PowerShell); exit 0. Log: `/tmp/cota-deploy-node.log`.
- Static checks: 231 first-party files syntax checked; Ruff passed. `git diff --check` passed. All three example agent configurations validated as service.
- No real provider requests, remote execution backend, Pi source modifications, commits or deployment performed.
