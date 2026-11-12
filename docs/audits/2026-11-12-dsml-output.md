# DSML output at the execution limit

## Observed failure

The configured picture-book Bot's latest run reached its first reserved wrap-up request at model decision 99 (98/100 already used). The saved provider response contained DSML `calls/invoke/parameter` text, no structured tool calls, and `stopReason=stop`. Cota persisted it as `bot_utter` and marked `hasFinalReply=true`. The run ended as `limited`; the proposed `read` did not execute. This was an invalid model output accepted by Cota, not evidence of task completion.

The preceding requests declared seven tools. The wrap-up request declared none, as designed, but did not explicitly set `tool_choice`. Pi's installed OpenAI provider exposes `toolChoice`; DeepSeek documents that `none` is also the no-tools default, so omission alone does not establish the upstream cause. A plain-text tool attempt must be handled even when the provider ignores or mishandles the parameter.

## Corrected boundary

- The pinned Pi provider receives `toolChoice: none` for wrap-up; custom Python adapters receive the equivalent parameter. Pi remains the only model/tool loop.
- One incremental guard recognizes the observed reserved DSML markers outside Markdown code examples. Possible split marker prefixes are withheld from live preview. Inline examples are buffered until a real matching delimiter; escaped or unmatched inline ticks cannot exempt the rest of a reply. Backtick/tilde fenced examples are supported, including Markdown's fence-to-EOF behavior. Normal prose streams immediately; quoted content can wait for its delimiter/EOF and is bounded by the provider's response budget. This is a protocol-output check, not a general content sanitizer or DSML interpreter.
- The raw assembled response is saved before validation. Rejected decisions receive Debug status `rejected` and `error_type: ToolProtocolText`; they generate no bot/tool facts and never execute even an accompanying structured call batch. Pi receives an empty rejected decision solely to finish that turn normally.
- For wrap-up only, `finishTurn` may request one corrective text response within the remaining original model budget. The rejected response is not included in the next request. A valid reply must still be durably acknowledged before it counts as a final answer.
- Exhausted correction or an invalid response during ordinary execution produces an explicit Cota fallback. Run status is `limited` for forced wrap-up or `failed` for ordinary protocol failure; run metadata identifies the error. No extra Event type, public Bot setting, provider-package change or retry loop was added.
- Previously persisted protocol-only assistant replies remain historical evidence; the outgoing working-context projection omits them without altering stored events. Structured tool carriers remain intact so tool-result pairing is preserved.

## Regression entry points

`cota/runtime/pi/output.test.mjs`, `budget.test.mjs`, `model.test.mjs` cover every split boundary of representative markers, quoted-code preservation, native HTTP `tool_choice`, one bounded Pi correction, no side effects from mixed malformed batches, raw evidence and restored-context filtering.

`tests/test_protocol_output.py` exercises the real Python/worker/Pi path with deterministic custom-model responses, plus native observer diagnostics with Debug on/off. It checks delivery, the original ten-call budget, eight actual tool effects, failed-correction fallback and Store replay equality. `tests/test_pi_distribution.py` guards inclusion of `output.mjs` in native release bundles.

All provider verification uses local responses; this task does not call paid models, modify the live conversation database or rewrite the existing picture book.

Read-only review found and reproduced an initial escaped/unmatched-backtick bypass and a tilde-fence false positive. Both received failing-first regressions; re-review confirmed rejection without streaming DSML, byte-exact legitimate fenced examples, and correct escape parity. No review findings remain open.

Final verification: full Python suite **1744 passed, 2 skipped** (336.72s); after the quote-boundary correction, Runtime/trace/packaging regressions **119 passed** (51.60s); full Pi Node suite **141 passed, 2 platform skips**. Ruff, compileall and `git diff --check` passed. Logs are `/tmp/cota-dsml-full-python.log`, `/tmp/cota-dsml-runtime-final.log` and `/tmp/cota-dsml-node-final.log`. The private picture-book's distributable files still match the repository template, excluding credentials; no Bot configuration change is needed. Restart Shell to load both Python and Node changes. No commit or push was requested.
