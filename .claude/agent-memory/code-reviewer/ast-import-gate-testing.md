---
name: ast-import-gate-testing
description: how to adversarially test an AST-based import allowlist or prohibition test; each fix round has left a further plain-literal shape live
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

**Round two shapes, once the `ast.Call` walk above exists (UNIT-006 round
two):** a bare `Name` call target from `from importlib import import_module;
import_module("y")`, invisible if the walk only matches `ast.Attribute` with
`.attr == "import_module"`; and the keyword form `import_module(name="y")`,
invisible if the walk only inspects `node.args[0]`. Both are plain literals in
ordinary, idiomatic Python, not contrived. Fix by matching `ast.Name` with
`id in {"import_module", "__import__"}` too, and by scanning
`node.args + [kw.value for kw in node.keywords if kw.arg in {"name", None}]`
(the `None` arg name is the `**kwargs` splat; its `keyword.value` is a `Name`
or `Dict`, not a `Constant`, so it is filtered out for free and cannot crash
or false-positive the literal check).

**Round three shapes, once round two's fix exists (UNIT-006 round three):**
two more plain-literal evasions, neither "computed" in any sense the
concatenation/rebound-alias residual limit already named. `import_module(f"y")`,
an f-string with zero placeholders, parses as `JoinedStr(values=[Constant(...)])`
rather than `ast.Constant`, so a check that only accepts `ast.Constant` misses
it even though the value is fixed at parse time; this is the stronger,
headline-worthy one, since nothing about it reads as "run time." Weaker but
still real: a literal assigned to a variable first and passed by name,
`_pkg = "y"; import_module(_pkg)`, or the same shape reached through a `for`
loop over a literal tuple, `[import_module(m) for m in ("y",)]`; both need a
one-hop constant-propagation the AST walk does not do. Report the `JoinedStr`
case as the primary finding when both are present, since a reviewer given only
the variable-indirection case can argue it about whether a name lookup counts
as "computed," and that argument has no purchase against a zero-placeholder
f-string. The fix for `JoinedStr` is symmetric with the round-two fix: extend
the same shared "is this argument a literal `y`" predicate to accept
`ast.Constant` with a `str` value OR `ast.JoinedStr` whose `values` is exactly
one such `Constant`, applied to both `node.args` and the keyword scan so
`import_module(name=f"y")` cannot reopen the positional/keyword split that
caused round two. Each round's docstring claimed its residual limit was now
accurate and each time a further plain-literal shape was still live; treat
that claim as unverified until you have personally tried an f-string and a
variable-indirected literal, not just the shapes the previous round named.
