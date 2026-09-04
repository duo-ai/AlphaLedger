---
name: ast-import-gate-testing
description: how to adversarially test an AST-based import allowlist or prohibition test, and the one class of import it structurally cannot see
metadata:
  type: feedback
---

When a unit's test suite enforces "only module X may import package Y" (or
"nothing may import Y") by walking `ast.Import` and `ast.ImportFrom` nodes,
that check is sound against every syntactic import form: `import y`,
`import y as z`, `from y import a`, `from . import y`, an import nested inside
a function body, an `if` block, or a `TYPE_CHECKING` guard. `ast.walk` visits
the whole tree regardless of control flow, so none of those hide from it.

**Why:** the one form that reliably defeats it is a dynamic import,
`importlib.import_module("y")` or the builtin `__import__("y")`, because that
is a runtime `ast.Call` on a string literal, not an `Import`/`ImportFrom` node
at all. Verified empirically on UNIT-006's `tests/test_dependencies.py`: a
scratch file doing `import httpx as h` correctly failed the allowlist test;
the same scratch file rewritten as
`httpx = importlib.import_module("httpx")` passed all five tests in the file
with a clean `git status` afterward. This is exactly the reviewer-brief
category "tests that do not exercise the claimed path," not a hypothetical.

**How to apply:** whenever reviewing a unit whose contract or AC leans on an
`ast`-walked import gate (this repo has at least one, `tests/test_dependencies.py`,
and more are coming as UNIT-031/UNIT-028 populate its allowlist), do the
empirical attack: add a scratch file under `src/` using
`importlib.import_module("<package>")`, run the narrow test file, confirm it
stays green, then delete the scratch file and confirm `git status` is clean.
If it passes green, that is a real, demonstrable gap and worth reporting at
HIGH under this repo's stated priority category, not a theoretical nitpick.
The fix is cheap: also walk for `ast.Call` nodes whose `func` resolves to
`importlib.import_module` or `__import__` with a string-literal first
argument equal to the package name or a dotted prefix of it. That still will
not catch a fully computed/obfuscated string; state that residual limit in
the test's own docstring rather than leaving it implied.
