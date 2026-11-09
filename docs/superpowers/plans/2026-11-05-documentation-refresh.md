# Cota Documentation Refresh Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement the assigned documentation scope. Work in the current feature/2.0 tree because the documentation must describe its existing uncommitted implementation; do not create a checkout that omits those changes. No commit or deployment is requested.

**Goal:** Make all published Cota documentation describe the agreed Bot development/deployment platform and the actual Pi Core + Skill + Tool + Event/Trace + Policy implementation.

**Architecture:** Cota owns Bot configuration, business guidance, state/persistence and application coordination. Pi Agent Core owns the model/tool loop; Pi coding-agent supplies Skill resource components, not AgentSession persistence. Application/Channel and the optional Web app have separate responsibilities. RSI and self-contained sandboxed Bot packages remain future work.

**Tech Stack:** Markdown/mdBook, existing static landing HTML, Python configuration validators and CLI, offline documentation/link/example checks.

## Tasks

- [x] Inventory every published and orphan documentation page; compare configuration, commands, events and module responsibilities with current code. Treat audits/plans/specs as historical records outside the current handbook.
- [x] Update module references: `concepts/{agent,execution-flow,pi-runtime,dst,llm,message,tool-adapters,channel,task}.md`, `components/{mcp,scheduler,user_memory}.md`, `configuration/{agent,endpoints,overview,policy}.md`. Explain normal/debug records, immutable events, snapshots, identity, execution and resource boundaries. Use actual supported config keys and APIs; remove obsolete claims.
- [x] Rewrite entry/positioning and deployment material: root README, handbook introduction, architecture, landing page, installation, quick start, deployment guide/configuration/troubleshooting; retain accurate detailed application/Web/group/delivery pages and align them with code. Show link/service sharing and folder sharing separately, plus explicit delivery limits.
- [x] Audit Skill/Policy examples and training/inference descriptions against catalog/factory/runtime; retain approachable `policies/name/steps` annotation with ordered `thought/skills/result/reply` items. Explain guidance rather than hard routing, and no hidden chain-of-thought capture.
- [x] Reorganize SUMMARY into user journey and module reference, add module map, development/testing and roadmap pages, remove mdBook placeholder chapters and obsolete design notes from current navigation. Update mdBook metadata and build configuration only as required to build the handbook.
- [x] Validate all handbook links, SUMMARY coverage, local resources and YAML examples with the real validators. Run CLI help and offline focused config/annotation/template tests, and build mdBook if installed or locally obtainable. Spec-review then quality-review changed docs against code; correct all factual gaps. Do not run live provider calls or publish the site.

## Acceptance

Readers can define a Bot, configure endpoints, run shell/debug, edit/train policies, understand a complete turn and persisted events, choose application/channel/Web app boundaries, and share a service or folder without relying on deleted APIs. Current capability and future RSI/package goals are clearly separated. No business/runtime code changes are needed for this documentation task.

## Verification completed

- Final spec review and independent documentation quality review passed; corrected class names, init paths, conditional read naming, MCP process ownership and allow_from startup semantics.
- mdBook 0.4.36 built successfully. Replacing its index with the landing page as in Pages CI retained the handbook introduction; 45 generated HTML files and 3,612 local links/assets/anchors checked without errors.
- Checked 48 Markdown files, 220 local links and complete SUMMARY coverage. Parsed 31 YAML examples; 6 Policy and 11 Agent configuration blocks passed the actual validators. All 16 Python examples passed syntax checks.
- Module examples additionally passed actual temporary SQLite Agent loading/cleanup and Event/DST snapshot replay checks.
- Focused config, Policy, annotation CLI, templates and CLI lifecycle tests: 73 passed, with one existing websockets deprecation warning.
- Documentation whitespace checks passed. No live model/platform calls, wheel publication, website deployment or business-code changes were performed for this task.
