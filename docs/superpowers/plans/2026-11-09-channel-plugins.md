# Channel Plugins Implementation Plan

> Execute the approved Channel extension design in this session with TDD and independent review.

**Goal:** An independently installed Python package can run a webhook/REST Channel under `cota run`, without modifying Cota source.

**Architecture:** A per-application registry resolves built-ins, explicit factories and `cota.channels` entry points. Channels retain protocol ownership; bound contexts submit through Application. HTTP routes mount before server startup, while the existing Manager and Store own lifecycle and durable delivery. Debug remains a separate loopback-only reader.

**Tech stack:** Python 3.12, importlib.metadata, Sanic, existing Application/Store/DeliveryDispatcher, pytest.

### 1. Discovery and registration
- [x] Add `cota/channels/registry.py` and `tests/channels/test_registry.py`.
- [x] Test built-ins, lazy entry point loading, duplicate names, unknown types, disabled plugins, explicit factories and multiple instances.
- [x] Verify failures before implementing; run the focused registry suite after implementation.

### 2. Runtime contract and manager
- [x] Add a bound ChannelContext and BaseChannel receive/mount/task supervision contract.
- [x] Replace hardcoded creation/permission/readiness rules with registry creation and adapter validation.
- [x] Prepare adapters without I/O before HTTP route registration; bind Application receive before startup.
- [x] Preserve group semantics, per-session scheduling, durable outbox and orderly resource shutdown.
- [x] Add regressions for durable admission, identity binding, startup failures and background task failures.

### 3. HTTP and service debugging
- [x] Let server validate generic channel mappings and mount adapter Blueprints under `/channels/{instance}`.
- [x] Keep Web-specific browser middleware scoped to Web endpoints; reject route collisions and asynchronous mount factories.
- [x] Launch separate read-only debug viewer for `cota run --debug`, with bounded session browsing and delivery inspection.
- [x] Cover external-only service startup, callback receipt, retry/restart without repeated model execution, and debug queries.

### 4. Deliverable example and documentation
- [x] Add a separately installable sample webhook/REST plugin, with entry point metadata, validation and idempotent outbound sends.
- [x] Document installation, configuration, ID/scope contracts, lifecycle, auth responsibilities, durable ACK and debug boundaries.
- [x] Update Channel/config/API docs and README link.

### 5. Verification and review
- [x] Run focused tests, installed-package discovery smoke test, Python checks/full regression and relevant browser tests.
- [x] Review approved requirements and code quality; fix verified findings and rerun affected tests.
- [x] Report exact usage and remaining platform-specific requirements. No SeaTalk credentials or real platform calls are required.


## Verification results

- Final `scripts/check.py --coverage`: 1,422 Python tests passed, 2 skipped; branch coverage 87.27% (gate 76%).
- JavaScript: 82 passed, 2 skipped, including actual Debug UI session-switch regressions.
- Independent Hatchling package build and installation to a temporary target passed. A Python process outside the checkout discovered the real installed entry point, loaded its installed module, bound an instance and mounted its HTTP route.
- Real localhost HTTP/Pi/SQLite integration verified admission ACK, duplicate input, REST failure and restart delivery using the same event ID without another model execution.
- Review findings fixed and retested: immediate listener admission during startup, fail-fast startup errors, stale Debug session responses, invalid factory awaitables and exception-secret redaction.
- Debug listener failure leaves the Bot service running. Local documentation links and source syntax/lint checks pass.
- Implementation remains on `codex/channel-plugins` for review; no platform credentials, real SeaTalk API calls, or package publication are required for verification.
