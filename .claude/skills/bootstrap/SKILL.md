---
name: bootstrap
description: Inspect and validate the local AlphaLedger development environment after clone or toolchain changes.
disable-model-invocation: true
---

# Bootstrap AlphaLedger

Run from the repository root. Do not install globally, alter credentials, or
create application code.

1. Read `AGENTS.md`, `project-state/STATUS.md`, and
   `project-state/DECISIONS.md`.
2. Report `claude --version`, `uv --version`, and `python3 --version`. Claude
   Code 2.1.233 or later is required for the agent validator; Python 3.14 is the
   implementation target.
3. Validate strict JSON in `.claude/settings.json` and `.mcp.json` without
   expanding or printing environment values.
4. Run `python3 .claude/hooks/guard.py --self-test`.
5. Run `claude plugin validate .claude/agents` when the installed version
   supports it.
6. If both `pyproject.toml` and `uv.lock` exist, run `uv sync --frozen`. If
   neither exists, report that implementation scaffolding has not started. If
   only one exists, stop and report an incomplete lock state.
7. Run `claude mcp list`. Report only status and missing variable names; never
   print credential values. The Alpaca server must expose market-data toolsets
   only.
8. Run the repository's defined fast quality gate if present.

Return a table of `check`, `observed`, `status`, and `next action`. Do not claim
the environment is ready if any safety check, lockfile check, or MCP scope check
is unresolved.
