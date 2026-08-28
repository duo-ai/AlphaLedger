# AlphaLedger project status

Last updated: 2026-08-27

## Current phase

Pre-kickoff planning and harness preparation. The replanned architecture and
execution schedule exist; application scaffolding has not started. This package
is a launch kit, not evidence that any gate has passed.

## Active gate

G0 — competition rules, account, permissions, data entitlements, integration
versions, and submission requirements remain unverified for the actual event
environment.

## Verified artifacts

- `options-alpha-agent-design.md`: canonical system design.
- `hackathon-build-plan.md`: execution-first schedule and gates.
- `orchestrator-system-prompt.md`: runtime orchestration and news schema.
- `.claude/`: project-scoped Claude Code harness based on current official
  documentation and maintained examples.
- `.codex/` and `.agents/skills/`: project-scoped Codex harness based on
  current official OpenAI documentation.
- `.mcp.json` and `.codex/config.toml`: Alpaca MCP 2.3.0 pinned with
  market-data-only toolsets for their respective runtimes.

## Not yet verified

- competition paper account identity, starting balance, and options level;
- OPRA versus indicative options entitlement and equity feed mode;
- current MLeg request behavior in the competition environment;
- event rules on pre-kickoff code and required submission artifacts;
- Python project, lockfile, application tests, and every G1–G6 artifact.

## Next three tasks

1. At kickoff, record official rules and actual account/feed facts in the run
   manifest and pass or block G0.
2. Scaffold the pinned Python project only when event rules permit; implement
   the paper endpoint assertion and order adapter contract first.
3. Run the manual paper-smoke dry run, obtain execution-safety review, then
   perform the one-contract paper lifecycle only with explicit human
   acknowledgement.

## Read first next session

1. `AGENTS.md`
2. `hackathon-build-plan.md` sections 2–4
3. `options-alpha-agent-design.md` sections 0–4 and execution/risk sections
4. `project-state/DECISIONS.md`
