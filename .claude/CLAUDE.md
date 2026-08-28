@../AGENTS.md
@../project-state/STATUS.md
@../project-state/DECISIONS.md

# Claude Code runtime notes

- Start Claude Code from the repository root. Project settings are scoped to
  the directory where the session starts.
- Treat imported project state as a checkpoint, not proof. Verify it against
  the current tree and broker truth before acting.
- Use the main session for edits. Delegate only bounded analysis or review to
  the specialist agents in `.claude/agents/`.
- The configured `alpaca` MCP server deliberately omits `account` and
  `trading`. Never broaden its toolsets in a committed file.
- Invoke `/bootstrap` after cloning, `/research-gate` before freezing alpha,
  `/paper-smoke` only for a human-controlled paper test, `/handoff` at a useful
  checkpoint, and `/submission-readiness` before the final freeze.
- Update only the canonical files under `../project-state/`; do not create a
  Claude-specific duplicate checkpoint.
- Do not set a project-wide default agent or bypass-permissions mode. Keep
  model choice and personal approvals in `.claude/settings.local.json`.
