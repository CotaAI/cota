# Basic Chat Reliability and Cota 2.0 Release Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Keep the existing feature/2.0 working tree; it contains the authorized major-version implementation. Do not discard prior changes or commit local credentials/state.

**Goal:** Deliver reliable basic chat with external identity ownership, distribute only weather, validate and publish Cota 2.0.0 source on main.

**Architecture:** Application persists accepted inputs before scheduling. Direct execution uses a detached causal view just like group execution, so new messages can be saved while Pi runs. Web subscriptions and optional chat state implement delivery/read synchronization, without adding an account system or putting reading state into DST.

**Tech Stack:** Python 3.12, Sanic, SQLAlchemy/SQLite, native WebSocket browser client, official Pi Core, Hatch and GitHub Actions.

## Task 1: Durable intake and causal execution (root)
- [x] Add regressions proving a queued direct input is in Store before return, duplicate retries do not execute twice, later inputs do not enter an earlier run, and a process restart can discover unstarted work without reexecuting started tool runs.
- [x] Persist user_utter in Application intake under admission lock; use Store receipt facts and a bounded recovery dispatcher. Preserve group observed-message behavior and channel-neutral IDs.
- [x] Add Processor entry for recorded direct input using detached execution_view and save_execution; retain direct Processor API for eval/shell.
- [x] Expose bounded recent/backward message pages and basic conversation summaries from Application/Store. Public messages include timestamps. Keep read cursors outside DST.
- [x] Verify Application, Store, Pi, group, Web and delivery contracts.

## Task 2: Minimal chat synchronization (worker)
- [x] Implement bounded authorized multi-conversation subscriptions; no identity provisioning added. Keep existing authentication/authorization adapters as the boundary.
- [x] Add basic last-message/last-active/unread/read cursor APIs to optional chat application; authorize all calls, keep正文 in Store and read state outside DST.
- [x] Add recent-history/backward paging and bounded resilient client cache. Protect against corrupt storage/quota failure; do not silently discard unsent inputs.
- [x] Enforce connection/subscription capacity, retain slow-client isolation; expose basic non-sensitive runtime status.
- [x] Test replay/live ordering, membership revocation, paging, read state, multiple rooms, cache corruption/quota and cancel cleanup.

## Task 3: Weather-only distribution (worker)
- [x] Remove hello/pet from shipped bots; preserve reusable test coverage through test-owned fixtures where appropriate.
- [x] Update init/package/smoke tests and active docs so only weather is advertised. Do not delete users' generated projects.
- [x] Verify template filtering and init from outside the repository.

## Task 4: Release preparation and integration (root)
- [x] Inspect remote main, default branch and release credentials without printing secrets; choose 2.0.0 for breaking changes.
- [x] Add source release notes and keep test/build validation; user clarified no binary attachments or PyPI publication.
- [x] Run full source/static/Python/Node checks and installed-wheel smoke; review bundled files for credentials/local state.
- [ ] Commit the authorized major-version source, integrate remote main without force push, publish main and v2.0.0, and verify remote source/CI. Do not publish binary release assets or PyPI packages.
