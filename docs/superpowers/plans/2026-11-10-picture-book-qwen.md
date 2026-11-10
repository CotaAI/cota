# Picture-book Qwen configuration

User selected qwen-image-3.0 for generation/editing and qwen3.8-omni-flash
for vision at their supplied compatible-mode base URL. Keep credentials only
in an owner-readable deployment outside the Git checkout; use the vision model
for the main tool-calling conversation too. No real paid calls in this task.

Official Qwen Images protocol uses JSON /images/generations for both generation
and reference-image editing, accepts real data-URI references, and returns URLs.
Add explicit image.api=qwen selection in this Bot's existing adapter. Preserve
the default OpenAI multipart/base64 path. Download generated images only from
approved HTTPS hosts, without API Authorization, redirects, or oversized bodies;
never expose signed URLs in errors/journals. Qwen 3.0 reference limits apply before
any model request. Core Cota/Pi and prompt/model-resource design are unchanged.

- [x] Add failing tests covering Qwen generation/editing, URL download, no leaked
  credentials, error/limit handling and pre-call reference validation.
- [x] Implement the Bot-local adapter, config validation and command help/docs.
- [x] Run focused Bot/template/attachment tests and syntax/Ruff checks.
- [x] Copy the Bot to /Users/mingguang.shao/work/cota_projects/picture-book,
  write private endpoints.yml mode 0600, and check doctor plus Agent load offline.

Verification: initial tests reproduced eight failures before implementation; the
final focused run passes 95 tests (three existing websockets deprecation warnings),
including 36 picture-book cases. Logs: /tmp/cota-qwen-verification.log and
/tmp/cota-qwen-static.log (258 sources, syntax/Ruff passed). Independent read-only
review found no blockers. The private doctor reports ready=true, Agent loads with
vision enabled, and all repository template credentials remain empty. A separate
authenticated GET /models returned HTTP 200 and listed both requested models;
no real inference/generation requests were made. The supplied key was entered
through hidden terminal input, never command arguments or output. No commit/push.
