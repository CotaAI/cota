# Bot examples cleanup and regression plan

Approved direction: Cota owns Bot definitions, business policies, DST and Store; Pi Agent Core owns execution.

1. Retain hello (minimal conversation), migrate pet (business conversation), and weather (Skill + policy + HTTP + pause/resume). Remove duplicate test_qa/test_weather and obsolete agent_browser/computer_use/xianyu demos that depend on retired execution/configuration. Preserve local files and endpoint credentials in a private temporary backup first.
2. Standardize configs, least-capability tool lists, environment-referenced model credentials, Bot-local SQLite storage, README and weather SOP using registered tools.
3. Make cota init non-destructive and exclude runtime artifacts from template copying.
4. Exercise actual copied Bots through Agent, Processor, Pi, tools and SQLite with deterministic external model/HTTP responses. Test restart/resume, isolation, policy injection, tool failure and denied tools. No live credential use required.
5. Run full Python/Node regression; verify built-wheel templates and init outside the repository. Document the difference between deterministic integration tests and live model/service validation.

## Outcome

- User refinement honored: pet retained and migrated to Pi as a business conversation example; only duplicates and demos requiring missing browser/desktop/shell integrations removed.
- Standardized three Bots with environment model config, explicit tool policy, Bot-local SQLite and current documentation. Removed stale generated frontend caches and packaged runtime data.
- Tests exposed and fixed LLM environment references, SQLite relative path handling, destructive init, MatchDPL indexing the future action, and missing role interpolation in custom prompts. Interactive instructions corrected to `cota shell`.
- Private backup of original templates, endpoint credentials and local artifacts: `/tmp/cota-bots-backup-j0tg04yr` (directory 0700/files 0600). Backup is temporary and not a published artifact.
- Full Python regression: 500 passed, 7 skipped (existing warning categories remain). Node/Pi: 6 passed. Final focused template/real-Bot suite: 15 passed after hidden-cache exclusion fix.
- Built macOS arm64 wheel and verified exactly 13 intended Bot files. Reinstalled outside the checkout; CLI/init/three real Pi Bot runs passed with no system Node/npm or network. Installed `cota shell` startup and `/stop` exit verified.
- Independent review findings fixed and rechecked. No live model/provider or live weather quality validation claimed; external HTTP responses in integration tests are deterministic.
