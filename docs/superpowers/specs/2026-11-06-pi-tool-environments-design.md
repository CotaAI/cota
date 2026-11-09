# Pi tools and Cota execution environments

Approved in the tool-design discussion and implementation request of 2026-11-06.

Pi owns read/write/edit/bash schemas, argument preparation, reading/pagination/images,
editing/diffs, command output and the agent loop. Cota owns trusted environment binding,
tool availability, durable authorization/start/result checkpoints and Skill provenance.
Reuse published Pi 1.4.0 ToolDefinition factories, whose execute contract also works with
Agent Core; preserve their prompt guidelines without importing a coding-agent session.

First release supports `environment: {type: none}` (default, only discovered Skill files
readable) and `environment: {type: host, workspace: ./files, timeout_seconds: 60}`.
Host requires an explicit workspace; relative paths resolve against the Bot directory.
Workspace is an initial directory, NOT a sandbox. Host tools have the OS account's rights,
including absolute paths, inherited environment and network. Host is a trusted deployment,
not per-user filesystem isolation; all users of that deployment share that host. Public
services should use none until a real isolated backend is available. Unknown backends fail
configuration validation. Device/container support is deferred, never silently substituted.

The configured immutable environment is bound per runtime. Host working directory is
separate from Bot resources and Cota's workspace (Store/logs). Core tool names are reserved;
`tools.allow/deny` applies to Cota extension tools. Native tools are authorized before each
execution after their start checkpoint. Results are acknowledged before the loop proceeds.
Skill reads attach compact resource provenance to the existing tool_result, and all other
native outcomes retain useful diff/exit/artifact facts without full duplicate output.
Environment identity is run metadata, not a new event or model-controlled argument.

Bridge cancellation must abort Pi tools, including shell process trees. No automatic tool
retry or rollback. Shared-file write coordination from Pi is process-local, not a database
lock; host mode does not promise concurrent-user transaction isolation.

Validation covers real factory IO, absent Skills, no-host access, config rejection, prompt
contributions, multi-turn trace restoration, authorization revocation, checkpoint failure,
command timeout and bridge cancellation. Existing Pi/Skill/Policy and full Python suite
must remain green. Templates and docs explain the opt-in and deployment boundary.
