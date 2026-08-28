# AlphaLedger accepted decisions

Only accepted, consequential choices belong here. Experiments and open ideas
belong in the trial registry or status file.

## D-001 — Paper-only system boundary

- Date: 2026-08-27
- Decision: AlphaLedger has no live-money endpoint or generic live-mode path.
- Rationale: competition scope and irreversible-risk containment.
- Revisit only if: a separate future project is explicitly authorized and
  independently threat-modeled. Do not relax this repository in place.

## D-002 — Cross-sectional forward alpha

- Date: 2026-08-27
- Decision: scan a frozen liquid universe and forecast future residual returns
  from independent price/volume and point-in-time news families.
- Rationale: replaces the original single-ticker, contemporaneous-event story
  with a pooled, falsifiable prediction problem.
- Revisit only if: chronological evidence rejects the design; the fallback is
  a separately validated price-volume model or no live alpha, not ticker hunting.

## D-003 — Execution-first vertical slice

- Date: 2026-08-27
- Decision: prove submit, reconciliation, monitoring, exit, restart recovery,
  and ledger behavior before UI or additional strategies.
- Rationale: autonomous paper operation is core evidence, not a cuttable extra.
- Revisit only if: official rules prohibit paper access; then preserve the state
  machine with recorded fixtures and disclose the limitation.

## D-004 — One writer, specialist reviewers

- Date: 2026-08-27
- Decision: the main coding-agent session owns edits; project subagents are
  bounded, read-only research and review specialists.
- Rationale: avoids concurrent checkout mutation and keeps a human-visible
  permission boundary around changes to trading code.
- Alternatives rejected: autonomous write agents and a default coordinator
  agent, which add state, permission, and merge complexity during a solo sprint.
- Revisit only if: work is split into independent repositories or explicitly
  isolated worktrees with a reviewed integration protocol.

## D-005 — Python 3.12 with uv

- Date: 2026-08-27
- Decision: use Python 3.12, `uv`, a committed lockfile, and typed boundaries.
- Rationale: strongest fit for Alpaca, data research, modeling, and a one-week
  implementation while keeping deterministic services testable.
- Revisit only if: event infrastructure mandates another runtime before code is
  scaffolded. Do not introduce a second application language during the sprint.

## D-006 — Agent Alpaca MCP is market-data-only

- Date: 2026-08-27
- Decision: commit Alpaca MCP with `assets`, `stock-data`, `options-data`,
  `corporate-actions`, and `news`; omit `account` and `trading` in both coding
  harnesses.
- Rationale: official toolset filtering provides a simpler least-privilege
  boundary. Application adapters own account validation and paper orders.
- Revisit only if: a read-only account toolset becomes separately enforceable.
  Never add the trading toolset to committed coding-agent configuration.

## D-007 — Pin Alpaca MCP 2.3.0 at harness creation

- Date: 2026-08-27
- Decision: `.mcp.json` and `.codex/config.toml` pin
  `alpaca-mcp-server==2.3.0`.
- Rationale: 2.3.0 is the version declared by the official repository when this
  harness was built; an unpinned `uvx` dependency is not reproducible.
- Revisit only if: Day-0 contract tests justify a version change. Record the new
  version, source, schema delta, and test result before changing the pin.

## D-008 — Tool-neutral project state

- Date: 2026-08-27
- Decision: `project-state/` is the single checkpoint and decision-log location
  shared by Claude Code and Codex.
- Rationale: duplicated runtime-specific state would drift and make a restart
  dependent on which harness ran last.
- Revisit only if: a future runtime needs generated local state that cannot be
  represented in the canonical Markdown checkpoint.
