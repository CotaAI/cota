# Unified conversation attachments

User approved the design: stable attachment metadata on user_utter/bot_utter; local file bytes outside Event/Store; Web upload, authorized download, UI cards, history/reconnect; migrate picture-book from its private download server. No new Event types or identity/account system.

- [x] Test local file storage: scope, metadata integrity, bounded size, safe names, immutable copies, path escape/symlinks.
- [x] Add attachment contracts to messages, Event validation, deterministic context, dedupe, direct/group/recovery and public projection.
- [x] Add Web upload/download APIs using existing authenticate/authorize; return stable IDs, never bearer tokens in URLs.
- [x] Add a Pi-standard send_files tool and Cota-bound handling for personal workspace exports; commit bot_utter before delivery. Service deployment cannot export host paths.
- [x] Propagate references through reliable delivery; unsupported channels explicitly fail without retry loops; terminal prints local file locations.
- [x] Add browser client/UI upload, attachment-only sends, pending/reconnect persistence, authenticated download and group access revocation tests.
- [x] Remove picture-book serve.py/private token publishing; use normal cota run --chat-app and send_files. Retain picture-book-specific validation.
- [x] Run targeted red/green tests, independent review, static checks and full Python/Node regressions. Do not retry browser access denied in the prior turn.

Limits: 20 MiB per file, eight attachments per message; upload bytes over HTTP, WebSocket carries IDs. Local storage sidecars scoped to sessions need backup alongside Store. No expiry of durable file references. Default downloads require current conversation access, including after reconnect. No automatic PDF understanding; image/tool handling does not imply arbitrary document parsing.

Model input is explicit: llms.<name>.vision defaults false; opt-in for automatic small-image injection. Otherwise the model gets file metadata, an unread/size-limit notice and (personal only) its scoped local-copy path, so text-only models can delegate to a dedicated vision tool. Native Pi tools remain Pi implementations.

Independent review findings fixed and reproduced with regression tests: pure-text SDK without config_path must start, agent=None scheduling must work, large/unread images need explicit notices, and unsupported target channels must not advertise send_files. Old Web group forwarding test updated for the new optional attachment argument.

## Verification

- Full suite: 1452 Python passed / 2 skipped, 87.44% branch coverage; 85 JavaScript passed / 2 skipped. `/tmp/cota-attachments-verified.log`.
- Final pure-text content normalization preserves strings when no actual image blocks exist. Its red/green regression and the final focused suite (attachments, picture-book, Pi runtime, endpoint/LLM) passed: 67 tests. `/tmp/cota-attachments-final-verification.log`.
- Final syntax/Ruff: 257 first-party sources passed. `/tmp/cota-attachments-final-static.log`. Whitespace checks and documentation/DOM ID checks passed.
- Actual localhost HTTP/WebSocket tests cover upload limits, UTF-8 names, attachment-only sends, replay, group permission revocation and cross-session denial. Pi runs the actual standard send_files definition; copied bytes and stable outbox IDs are verified across retries.
- Independent review fixes verified; no remaining reported blockers. No real paid model calls, browser retry, commit/push or release.
- Picture-book now uses standard cota run --chat-app; 48 portable files, 10 held-out dialogue cases. Specialized anonymous token serving is removed.
