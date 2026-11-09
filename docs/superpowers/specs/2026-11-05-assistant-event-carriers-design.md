# Assistant messages carried by business events

Approved in the conversation: remove model_response from core events, preserve recoverable assistant decisions through bot/tool_started, and keep provider requests/responses in independent optional Debug storage. No old-event compatibility or user database migration.

## Contract

- A model-produced bot stores its text once and payload.llm with request_id, request_sequence, model alias, policy provenance, duration_ms and stop_reason. It owns one assistant message.
- A tool batch's first actual tool_started stores payload.llm with the same metadata plus message containing normalized content blocks and stop_reason. This includes the entire proposed batch, even not-yet-started calls. Mixed text/tool output stays in this message; internal narration is not automatically displayed as a bot utterance.
- Later tool_started events in that batch use payload.llm_event_id pointing to the first carrier. They must match one of its call IDs, names and arguments. No second assistant message is projected.
- Tool-generated bot events (ask_user/reply_user) link payload.tool_event_id to their own tool_started. They are presentation evidence, not another model decision; do not duplicate them in context.
- All anchors are session-local, backward references in the same run. Owner model requests have unique request IDs and run-local ordinals. Non-model bot messages remain valid and project ordinary assistant text.
- Model failures retain model_error. Successful auxiliary calls emit no core model-response event. Runtime-local ordinal counts include auxiliary calls. Debug can record failures, pending requests and outputs with no carrier.
- Persist a carrier before Pi can execute an external tool. Pi assistant message identity is acknowledged from the persisted carrier; no source IDs point to diagnostic records.
- Runtime response normalization produces the message Pi consumes. Final text after a successful reply_user is internal/suppressed, Debug-only, and is deliberately not restored as user-facing history. Empty successful model outputs are likewise diagnostic-only.
- Snapshot state schema increments. Full replay and snapshot suffix replay produce identical state without Debug. Existing guard against replaying interrupted external effects remains.
- Debug event details resolve request diagnostics from llm/request_id or through llm_event_id/tool_event_id. Payloads never embed full requests. Inspection does not mutate events.

## Validation

Real Pi with mocked models: pure reply, Skill read, mixed text/two tools, interrupted first tool, ask/reply deduplication, invalid arguments/missing tools, auxiliary calls, compression, second-turn restore; Memory/SQLite and Debug on/off. Reject forged/cross-run references and inconsistent tool identities. Verify core persistence failures stop tools while diagnostic failures do not. Migrate existing tests and docs; run full Python and Node suites.
