# Cmdline attachment input

User approved `/file <path>` to stage files, `/clear` to discard staged references,
text to send with staged files, and Enter to send files alone. Relative paths use
the shell's startup directory; absolute paths, `~`, quoted and escaped spaces work.
Adding files never invokes the model. Existing eight-file / 20 MiB limits apply.

Implementation stays in CmdlineChannel: parse paths without executing a shell,
reuse FileStorage.import_paths with the explicitly selected parent directory, and
submit canonical references through the existing InboundMessage path. The model's
workspace restriction is unchanged; local users may explicitly select outside it.
File copies persist independently of the source, and `/clear` only discards pending
references, following the existing retention policy. Errors preserve earlier files.

- [x] Add failing tests for staging, immutable copies, empty sends, clearing,
  quoted/relative/home paths, limits, invalid files, unsupported storage and routing.
- [x] Implement bounded asynchronous file import and concise terminal guidance.
- [x] Verify the real Cmdline -> Processor -> Pi -> Store image-input path.
- [x] Document commands and run Cmdline, attachment, channel and static regressions.

No extra command framework, Event type, tool, model call or dependency is needed.
Implementation continues inline in the existing workspace; unrelated edits remain.

Verification: the initial 16 cases failed before implementation, then passed. The
expanded Cmdline suite passes all 18 cases, including literal shell metacharacters
and preserving pending references after admission rejection. The combined channel,
attachments, Shell/debug, scheduling and picture-book regression run passed 273
tests (including the initial 16). Log: `/tmp/cota-cmdline-attachments-tests.log`.
The final source syntax/Ruff check covers 258 files and passes; log:
`/tmp/cota-cmdline-attachments-static.log`. No real provider calls or browser access.
