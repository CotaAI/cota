# Focused tool improvements

Goal: improve tool configuration and diagnostics while keeping business integrations outside Cota.

The user approved implementing the previous review with a narrower boundary. Cota validates registration/configuration, binds Pi tools, and records execution. External applications own API credentials, business authorization, idempotency and service-specific retries. No credential vault, gateway, automatic retries, new event type or new tool loader.

Implementation uses existing Python registry/runtime and the native Node HTTP AgentTool. Existing work is on feature/2.0 with unrelated uncommitted changes; edit in place without committing unrelated work.

- [x] Add failing registry/config tests: unknown groups, duplicate/reserved/invalid registrations, atomic process registration, unknown configured names before a run. Implement shared registration checks; keep SDK registration before first run possible.
- [x] Add failing HTTP tests for selected Content-Type/Retry-After headers and one-attempt side-effecting failures. Implement compact optional headers, without credentials, automatic retries or domain policies.
- [x] Add failing runtime tests for initial inventory saved only in Debug discovery metadata, with no state/event changes. Show the inventory in the existing Skills tab (renamed Skills & Tools); retain exact per-request tools in request diagnostics.
- [x] Document application-owned authenticated integration and failure semantics. Do not imply plain HTTP carries trusted Cota user identity or that headers are secret storage.
- [x] Run targeted Python/Node regressions, static checks, and broader suites if changes affect shared contracts. Record outcomes below.


Verification so far:
- Red: 21 registry/config tests failed for missing validation; HTTP metadata test failed for missing headers; six inventory tests failed for missing diagnostic inventory.
- Green: tool registration/process/HTTP Python checks 60 passed; broader tool/runtime/debug regression 242 passed, 2 skipped (dependency/platform); native HTTP 12 passed.
- Node combined Pi/HTTP/Debug/Web tests: 69 passed, 1 Windows-only skip.
- First-party static syntax check (224 files), Ruff and diff whitespace checks passed.
- Full Python suite: 1205 passed, 1 skipped; one old participation test fixture failed because it relied on duplicate registration. Updated that fixture to register the disabled tool once, retaining all permission assertions. Related participation/Skill tests: 28 passed. After full-suite completion, `pytest -q --lf --last-failed-no-failures none`: 1 passed. Thus all 1206 executed Python cases have passing verification; no remaining failures. Existing websockets deprecation warnings remain.
- Final static and whitespace checks passed. No changes to Pi packages, database schemas, Event types or external credential/authorization services.
