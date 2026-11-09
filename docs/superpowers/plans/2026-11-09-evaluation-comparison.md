# Weather evaluation coverage and machine-readable comparison

User authorized implementation: expand to 30 scenarios, audit scripting/structured outputs, improve version comparison foundations, document init-to-eval commands. No RSI optimizer or new annotation fields.

- [x] Expand policy/eval/data.yml to 30 distinct cases covering weather scope/clarification, prices/budget boundaries, missing/changed constraints, availability, unknown prices, task cancellation/switching and unsupported bookings. Avoid assuming injected HTTP failures.
- [x] Persist run and case summary metrics with exact denominators, unjudged criteria separate from inconclusive, rates in [0,1], no pass on incomplete execution.
- [x] Fingerprint selected evaluation cases independent of selection order; record actual source runtime identity, Preserve provenance when rejudging.
- [x] Make comparisons script-readable: comparability/reason codes, per-criterion changes, per-run summaries, same-cohort pass-rate delta; changed/missing cases never silently improve scores. Preserve evidence and Markdown reports.
- [x] Validate init copies all 30 cases, schema/aggregation/CLI/comparison failure cases and existing Pi execution integration. Update docs with endpoint configuration, optional train, eval and compare commands.


Validation completed:
- Shipped weather verification data: 30 cases, 43 turns, 87 criteria. No extra annotation fields introduced.
- Targeted evaluation/example/template regression: 91 passed before the last comparison-boundary additions.
- Final evaluator + real Pi init/CLI integration run: 56 passed. All 43 turns produced execution and judge artifacts using controlled model responses; this does not measure live model accuracy.
- Final evaluator unit suite after report refinements: 54 passed. Static syntax scan of 233 first-party files, Ruff, and diff whitespace checks passed.
- Machine summaries include skipped/unjudged requirements in denominators. Comparisons explicitly reject changed/missing cases, judge identity, incomplete runs and different time budgets for overall improvement claims. Same-Bot comparisons carry a variance/rejudge warning.
- No RSI optimization/application mechanism implemented. No changes to the user's private Bot or model credentials.
