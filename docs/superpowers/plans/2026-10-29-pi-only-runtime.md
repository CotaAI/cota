# Pi-only execution and tool adapters

The user approved removing legacy model loops while retaining Cota business state, policy, persistence and a thin tool integration layer. Execute in the existing feature/2.0 checkout, preserving prior uncommitted changes. No publication or commit is requested.

## Design

- PiAgentRuntime becomes independent: initialize Cota resources directly and retain the prompt, model-adapter and reply/finalization methods it actually calls. Delete runtime/base.py and runtime/agent_runtime.py; expose only PiAgentRuntime. Processor rejects dialogue.runtime=legacy with migration instructions and has no legacy reply branch.
- Delete the unused SkillExecutor model loop and Executor factory. Remove MCPExecutor's model orchestration while retaining its stdio MCP client and the actively used remote MCP pool/tools. Old paused DST snapshots remain readable by Pi; deleting an engine must not delete conversation data.
- Replace SkillRuntime/InlineRuntime/SubprocessRuntime with an explicitly configured SubprocessToolClient under executor/tool_process.py. It connects a deployment-supplied command to the existing JSON-lines tool-server protocol; no model calls, environment installation or implicit per-Skill process. ToolRegistry.connect_process registers ProxyTools atomically, refuses name collisions and owns process cleanup. Python FunctionTool and existing MCPClientTool remain the primary adapters.
- A tool process is shared only when a developer explicitly registers it on a Bot's registry. Serialize RPC calls, validate response IDs, terminate after timeout/cancellation/protocol failure to prevent stale responses or blind replay. Do not advertise this as a sandbox or an MCP protocol implementation. Credentials/environment and session-specific authorization remain the explicit responsibility of the tool deployment; no new automatic tenant sharing.
- Preserve Skill metadata/venv discovery helpers for reading old declarations, but correct documentation to state they do not automatically activate an environment. Warn on obsolete executable configuration instead of silently implying it runs.

## Execution checklist

- [x] Add failing tests for rejecting legacy runtime selection, standalone Pi inheritance/import surface and tool process registration, concurrency, failure cleanup and real Pi integration.
- [x] Detach Pi, remove Python model loops and factory/registration hooks; retain MCP transport.
- [x] Implement the small tool-process client and atomic ToolRegistry registration/cleanup; keep tool permission checks at Pi's Python execution boundary.
- [x] Migrate old runtime tests to behavior tests through Pi, including Skill switching, old paused snapshots, dynamic policy, history and context compaction. Remove tests which only assert obsolete sliding-window internals.
- [x] Update runtime/migration/tool-adapter docs and stale active comments. Preserve historical planning documents and unrelated examples.
- [x] Run targeted tests, full Python/Node regressions, native wheel build and fresh-installed offline smoke. Request read-only review and address concrete findings. Record platform limits and API/configuration breaks.

## Verification commands

Use `.venv/bin/python -m pytest -q tests/test_pi_cleanup.py tests/executor/test_tool_process.py tests/test_pi_runtime.py` for the initial regressions; missing client/imports and acceptance of legacy must fail before implementation. Use `.venv/bin/python -m pytest -q` and `npm test --prefix cota/runtime/pi` after migration. Build with `COTA_RUNTIME_DIR=$PWD/.build/pi-runtime-public uv build --wheel`, inspect contents for removed modules, install into the clean test venv, and run scripts/smoke_installed.py from outside the checkout with networking and system Node/npm disabled.


## Results

- Full Python suite: 485 passed, 7 skipped. Existing pytest/event-loop, Sanic and LLM test cleanup warnings remain; no new failing tests.
- Pi Node suite: 6 passed. Tool-process suite: 13 passed, including real Pi invocation, policy enforcement, timeout/cancellation, concurrent and cross-registry ownership, scoped replacement, and POSIX descendants ignoring TERM after launcher exit.
- Independent review identified ownership and process-tree cleanup bugs; both were reproduced with failing tests, fixed and re-reviewed with no remaining blockers.
- Native macOS ARM64 wheel built and inspected: removed engine/factory modules absent; bundled Node/Pi and new adapter present. Installed via normal pip dependency resolution into a fresh Python 3.12 venv. pip check passed.
- Outside the checkout: installed Pi runtime/API imports passed; CLI and real Pi tool loop passed without system Node/npm or networking. No live model/provider requests were made. Other platform CI jobs have not run in this turn.
- Old AgentRuntime/Runtime/SkillExecutor/MCPExecutor execution APIs are removed. dialogue.runtime=legacy fails at configuration load; old executer fields and Skill runtime metadata emit migration warnings. Tool process registration is explicit; old paused AgentRuntime DST data remains readable.
- Changes remain uncommitted on feature/2.0. No PyPI publication or remote push.
