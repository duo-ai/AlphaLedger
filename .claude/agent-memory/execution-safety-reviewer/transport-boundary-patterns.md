---
name: transport-boundary-patterns
description: Patterns for reviewing a widened or new broker HTTP transport boundary (UNIT-010, UNIT-036, and any later transport/client unit).
metadata:
  type: feedback
---

Findings and reasoning worth reusing on the next transport-boundary review
(UNIT-006, UNIT-031, or any later widening of `broker/endpoint.py`).

## `f"{base_url}{path}"` with a single-leading-slash check is safe against `?`/`#`/`@` injection, given a standards-compliant parser

UNIT-036 widened `send_paper_request` to accept a query string on `path`. The
path check is `not path.startswith("/") or path.startswith("//")`, unchanged
from UNIT-010. Traced by hand against RFC 3986 authority-parsing: once a
parser reads `scheme://` and then consumes the authority component up to the
first `/`, `?`, or `#`, nothing later in the string can reopen authority
parsing. Since `base_url` is a fixed literal with no path of its own and
`path` is checked to start with exactly one `/`, the authority boundary is
fixed at that first slash regardless of what `path` contains after it,
including `@`, `#`, extra `//`, or an embedded `scheme://` substring. This
holds for `urllib.parse.urlsplit` and for any RFC-3986-conformant HTTP client
(httpx, requests, urllib3). It does **not** cover a transport that does ad hoc
string-based host extraction instead of standards parsing, and it does not
cover CRLF injection in `path` (request splitting), which neither UNIT-010 nor
UNIT-036 validates against; both are explicitly deferred to the concrete
client, out of scope for the Protocol-only unit.

**How to apply:** when reviewing a `base_url + path` string-concatenation
transport boundary, don't treat `?`/`#`/`@` in the path as an automatic
origin-injection risk merely because they exist. Actually trace the
authority-parsing boundary by hand (or note explicitly that you did). Do flag,
as a forward note rather than a blocking finding, that the concrete transport
(chosen in a later unit) needs to be confirmed as doing standards-compliant
parsing rather than ad hoc string matching, and that CRLF-in-path is
unvalidated at this layer if it's ever exercised by less-trusted input.

## A source-substring "no live host" test (AC-6 style) has the same blind spot as the AST import check, and check the guard hook before crediting it as a backstop

`test_the_module_still_admits_no_mode_switch_or_live_host` asserts
`source.count("alpaca.markets") == 1` and `PAPER_BASE_URL in source` against
the raw text of `endpoint.py`, with a comment claiming "the repository guard
refuses to let any file or command contain" the live host literal. It has the
same blind spot as the AST forbidden-import check documented in
`session-machine-patterns.md`: deliberately splitting the live host string
across two literals (for example `"alpaca.mark" + "ets"`) defeats the
substring count without the module containing the literal substring anywhere.

First pass graded this LOW on the strength of the comment's guard-hook claim.
That was wrong, caught only by actually reading
`.claude/hooks/guard.py::violation()`: for `tool_name in {"Read", "Edit",
"Write"}` the guard inspects only `tool_input["file_path"]` (via
`_sensitive_path`, which checks path sensitivity like `.env`), never the
`content`/`new_string` being written. The live-host regex
(`https?://api\.alpaca\.markets\b`) is checked only inside `_bash_violation`,
i.e. only against `Bash`/`PowerShell` command text. A coding agent that writes
or edits the live host literal straight into a source file via the `Write` or
`Edit` tool, which is the ordinary way source changes happen in this project,
is not blocked by the guard at all. So for that path, this AC-6 test actually
is the only line of defense, and its string-splitting blind spot is real and
unmitigated, not backstopped elsewhere as the in-file comment claims.

**How to apply:** when a unit's own test proves a safety property by grepping
its own source text (forbidden import, forbidden host, forbidden flag name)
and a comment or docstring claims another mechanism backstops the blind spot,
do not credit that claim without reading the named mechanism. This is the
same "check the claim rather than accepting prose that asserts it" pattern in
`session-machine-patterns.md`, now confirmed to bite even when the reviewer
already knows the pattern and is specifically asking whether a check is
sound. For this guard specifically: it protects Bash-command live-host
strings, not Write/Edit file content, so grade the substring-check blind spot
against source-file edits as unmitigated (MEDIUM here), not LOW.

## Verify a signature-widening unit's own "this breaks a merged caller" claim by grepping the whole tree

UNIT-036's own Verification section says "This unit changes a merged signature
that UNIT-011 and UNIT-012 call, so a green narrow run proves very little on
its own." A tree-wide grep for `send_paper_request`, `PaperTransport`, and
`TransportResponse` outside the unit's own two files found zero matches:
nothing in the merged codebase actually calls this transport yet (`broker/`
contains only `endpoint.py` and `__init__.py`). The claim was false against
the current tree, consistent with `STATUS.md`'s own statement that "no
transport submits anything to Alpaca." This didn't change the verdict (no
caller to silently break is strictly safer than a caller that broke
silently), but it's exactly the kind of intake claim that should be checked
rather than trusted, per the project's own "treat imported project state as a
checkpoint, not proof" rule.

**How to apply:** when an intake's Verification or Handoff section claims a
downstream consumer of the changed signature, grep the whole `src/` and
`tests/` tree for the changed symbol names before accepting the claim. Report
the actual result either way; a false "this breaks something" claim is minor
but still worth naming so the next reader doesn't inherit a wrong picture of
coupling.

## A test list's own promised per-dimension coverage (e.g. "under every verb") needs checking bullet by bullet against the actual test file, not just spot-checked

UNIT-036's test list promises "failure: a non-paper base URL is refused under
each of the four verbs, not only POST (AC-3)." The delivered test file adds
`VERBS`-parametrized tests for AC-1 (verb pass-through), AC-4 (redirect), and
AC-5 (path rejection), but the AC-3 host-rejection path
(`test_corruption_after_start_is_rejected_by_pre_submit_assertion`) was left
as the original single-verb (POST) test, not parametrized. The underlying
invariant is not actually at risk, because `assert_paper_endpoint` runs before
`method` is read anywhere in `send_paper_request`, so the check is
structurally verb-agnostic; this is confirmable by reading the function body,
not just asserted. Graded as a real, actionable, non-blocking finding: it's a
D-021 measurability gap against the unit's own written test list and a
numbered AC, but it doesn't demonstrate a concrete failure sequence, since the
code was read and shown incapable of the failure the missing test would
check for.

**How to apply:** when a test list enumerates "under every verb" / "under
every status" / "under every X" for several ACs, check each such bullet
individually against the actual parametrization in the delivered test file
rather than assuming a `VERBS`-style tuple used in some tests was used
everywhere it was promised. Distinguish (in the write-up) a gap that is purely
a broken promise from one that is also an unverified live risk, by tracing
whether the code path actually depends on the untested dimension.

## A mechanical "thread the new positional argument through every call site" edit can silently break an assertion that indexes the recorded tuple, and mypy will not catch it if both fields are `str`

UNIT-036 added `method: HttpMethod` as the first field `RecordingTransport`
records, changing `self.requests` from `list[tuple[str, bytes, bool]]`
(`url, body, follow_redirects`) to `list[tuple[str, str, bytes, bool]]`
(`method, url, body, follow_redirects`). One pre-existing assertion in
`test_redirect_contract_disables_following_and_rejects_replay` was never
updated to match the shifted index:
`assert all(not request[0].startswith(redirect_target) for request in
transport.requests)`. `request[0]` is now the HTTP method string (`"POST"`),
not the URL, so the assertion became `not "POST".startswith("https://...")`,
vacuously true regardless of whether a replay occurred. mypy is silent: both
tuple positions are `str`, so `request[0].startswith(redirect_target)`
type-checks whichever field ends up at index 0. Confirmed by reading the
merged pre-diff test file directly (`git show develop:tests/execution/test_endpoint.py`
equivalent, i.e. read the file at the primary clone, not the worktree): the
pre-diff tuple was 3-wide with the URL at index 0, so this line was correct
before the diff and was broken by the index shift the diff introduced.
Notably, this is the *second* time this exact "did the redirect actually
replay" assertion has been dead in this file: UNIT-010's own round-one review
found an earlier version of this same check was "theatre" for a different
reason (a transport structurally incapable of following a redirect at all).
Not independently exploitable this time, because a sibling assertion three
lines earlier (`transport.requests == [(...)]`, full-tuple equality) already
fully constrains the recorded call and would independently catch a bad
replay, so the safety property itself is not unguarded, only this one
particular assertion is dead weight.

**How to apply:** whenever a diff's own description says "every call site was
mechanically threaded with the new argument" (matching this diff's own item-6
framing), don't just check that call sites still compile. Grep every place
that indexes into a tuple/list the changed call also populates
(`request[0]`, `request[1]`, `.requests[...]`, etc.) and manually recompute
what each index now refers to. A same-type positional shift (str at index 0
before, str at index 0 after, different meaning) is invisible to the type
checker and invisible to a diff review that only checks "did the call site
get updated," so it has to be checked by re-deriving the tuple shape by hand.
