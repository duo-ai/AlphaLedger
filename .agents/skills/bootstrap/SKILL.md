---
name: bootstrap
description: Use only when the user explicitly invokes $bootstrap to inspect and validate the local AlphaLedger environment after clone or toolchain changes.
---

# Bootstrap AlphaLedger in Codex

Run from the repository root. Do not install global software, alter
credentials, mutate git, or create application code.

1. Read `AGENTS.md`, `project-state/STATUS.md`, and
   `project-state/DECISIONS.md`.
2. Report `codex --version`, `uv --version`, and `python3 --version`. Python
   3.14 is the application target; a different interpreter blocks application
   setup but not inspection of this planning package.
3. Parse every committed TOML and JSON configuration without expanding or
   printing environment values.
4. Run `python3 .codex/hooks/guard.py --self-test`.
5. Validate `.codex/rules/default.rules` with `codex execpolicy check` when the
   installed CLI provides that command. Confirm the destructive samples are
   forbidden and the paper-smoke command prompts.
6. If both `pyproject.toml` and `uv.lock` exist, run `uv sync --frozen`. If
   neither exists, report that implementation scaffolding has not started. If
   only one exists, stop and report an incomplete lock state.
7. Run `codex mcp list`. Report only connection state and missing environment
   variable names; never print values. The Alpaca server must expose only
   `assets`, `stock-data`, `options-data`, `corporate-actions`, and `news`.
8. Run the repository's defined fast quality gate if present.

Return a table with `check`, `observed`, `status`, and `next action`. Do not
claim readiness while a safety, lockfile, MCP scope, or trust check is
unresolved.
