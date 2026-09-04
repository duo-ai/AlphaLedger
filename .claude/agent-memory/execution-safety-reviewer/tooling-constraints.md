---
name: tooling-constraints
description: The execution-safety-reviewer's tool list is not guaranteed to include a shell/Bash tool in every invocation; check before promising to run commands.
metadata:
  type: project
---

The UNIT-033 review (2026-09-02) was launched with a tool list of Read, Write,
Edit, Grep, Glob, and advisor only. No Bash or shell-execution tool was
present, despite the review brief instructing "RUN, DO NOT ONLY READ" and
listing specific `uv run pytest` / `ruff` / `mypy` commands to execute and
specific mutations to inject and revert.

**Why this matters:** the harness prompt and the calling agent's instructions
can both assume shell access that the actual tool list does not grant. Silently
substituting static reading for execution and then reporting results as if
commands were run would violate the project's own definition of done ("Never
call a path verified when it was only inspected") and this role's mandate to
report exactly which commands were actually run.

**How to apply:** at the start of a review, check the actual tool list against
what the brief asks you to run. If no shell tool is available, do the deepest
static verification possible (read the test file and hand-count parametrized
cases against a claimed test count, trace AST logic by hand, enumerate table
entries manually) and say explicitly in the report that pytest/ruff/mypy were
not executed and why, rather than presenting inferred results as observed
ones. Do not ask to be re-invoked with more tools unless truly blocked; report
the limitation and give the best verified analysis available. This is a
per-session tool-list fact, not a permanent repository fact, so re-check it
each time rather than assuming it from this note.
