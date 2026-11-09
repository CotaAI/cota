# Complete Pi Native Tool Catalog Implementation Plan

**Goal:** Integrate Pi 1.4.0 grep/find/ls/powershell without changing Pi source or implementing another execution engine.
**Architecture:** Official ToolDefinition factories; host-only capability inspection via public Pi APIs. Use PI_OFFLINE to prevent runtime dependency downloads. Persist available/unavailable tool inventory in existing run metadata, and authorize only the inventory advertised for this run. Keep none restricted to Skill read.
**Tech Stack:** Python, Node ESM, pinned Pi 1.4.0, pytest, node:test.

Approved scope: existing none/host environments only. `environment.shell` accepts auto (available shells), bash, powershell, both. Explicit unavailable shells fail before model invocation. Pi PowerShell is Windows-only. rg/fd availability is tested using official tools against a temporary empty directory with bounded cancellation; no private Pi imports or copy of its executable resolver. Missing search binaries omit the corresponding tool and record why. Dependencies are installed by the deployment owner, never downloaded during a turn. Shell timeouts reuse Pi Operations; search cancellation and results use Pi unchanged.

- [x] Add failing config and real-tool tests: eight reserved names, host inventory, official ls/grep/find behavior, missing dependencies, PowerShell platform behavior, protocol authorization and trace restore.
- [x] Extend environment binding and config validation; add optional shell selection and persist its stable value.
- [x] Extend tools.mjs with official factories and bounded offline capability probes. Preserve native schemas, prompt hints, outputs and cancellation. Integrate run inventory before model invocation.
- [x] Validate inventory, persist it in run metadata, enforce exact advertised tool schemas, and retain compact native result details. No new event types.
- [x] Verify missing dependency and cancellation behavior. Update old four-tool assumptions and documentation. Run Node tests, focused Python regression tests, syntax/Ruff and whitespace checks. Broaden to full suite if integration regressions warrant it.

## Verification results

- Full Python regression: 1202 passed, 1 skipped; existing websockets deprecation warnings remain.
- Node regression: 51 passed, 1 skipped (official PowerShell execution requires Windows).
- Real grep/find tests used rg and an fd binary prepared by Pi itself under
  /tmp/cota-pi-catalog-test-deps. Runtime tests remained offline; Pi package source was not edited.
- Search cancellation, unavailable dependency omission, inventory persistence, schema authorization,
  listing limit metadata, and existing Skill provenance passed. Listing-limit assertion was also
  rerun separately after its final update.
- Syntax/Ruff passed for 230 first-party sources; Bot configs and CI YAML parsed; git diff --check passed.
- Added a Windows Node-only PowerShell CI job, not executed on this macOS machine. No claim of
  Windows end-to-end Cota deployment support or release publication.
