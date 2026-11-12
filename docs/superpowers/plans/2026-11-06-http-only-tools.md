# HTTP-only custom tool cleanup

**Goal:** Keep web_fetch as the only shipped custom tool, defined by Pi AgentTool; preserve official machine tools and plain-text reply delivery.
**Architecture:** Node owns HTTP tool schema/execution and uses the same authorization/checkpoint boundary as official Pi tools. Python retains only optional SDK/process adapters, Policy, resources and durable events. Remove eight builtin tools, old marker control-flow and default tool server. Keep memory, MCP and scheduler backends independently of model tools.

- [x] Red tests: no removed tools advertised, plain question + reply + replay, HTTP authorization and standard results.
- [x] Implement HTTP Pi tool with bounded response, checked DNS, cancellation, timeout and isolated tests (parallel worker).
- [x] Remove Python builtin definitions/loaders and reply/wait markers; wire HTTP schemas, live authorization and durable result acknowledgment.
- [x] Update Bot examples, policies and docs; migrate regression tests without dropping independent lifecycle/history guarantees (parallel workers).
- [x] Check Python/JS/static/packaging tests; inspect remaining legacy references; document verified results.


## Verified outcome

- Removed 8 builtin tool names and old Python HTTP class; no builtin bypass, private reply/pause markers or waiting lifecycle remain. Python FunctionTool/process adapters and memory/scheduler/MCP backends remain independent facilities.
- Added Pi AgentTool HTTP with TypeBox schema, checked DNS and URL targets, no redirects/proxies, bounded response, timeout/cancel, compact standard results. Bundle manifest and staged tests include the HTTP module.
- New red tests confirmed removed-tool advertisement and module checks failed before implementation. HTTP worker verified its red phase separately.
- Final Python: **1182 passed, 1 skipped**, 20 existing websockets deprecation warnings; **86.98% branch-inclusive coverage**, exceeding CI 76% gate. Exit 0. Log `/tmp/cota-http-final.log`, coverage `/tmp/cota-http-coverage.json`.
- Node full worker/HTTP/debug/web suite: **68 passed, 1 skipped** (Windows PowerShell). Final web status cleanup rerun: **19 passed**.
- Static: 224 first-party files syntax checked, Ruff and git diff whitespace checks passed.
- Independent integration review found no concrete introduced defects in authorization/checkpoint/replay/plain-reply paths.
- HTTP transport tests use local test servers; Bot scenarios use controlled model responses. No live model/provider requests or public API traffic, no commits or deployment.
