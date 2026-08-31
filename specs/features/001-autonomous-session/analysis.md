# Analysis: Feature 001, the autonomous paper trading session

Read-only pass over `specs/features/001-autonomous-session/spec.md`. No plan
exists yet, so the plan-cross-check half of the coverage and consistency
passes, and the "anything the plan names that the spec never asked for" check,
do not apply. They are not run rather than guessed at.

Verified against the working tree at the time of this pass (`develop` at
`1f732ac`), not against the checkpoint text alone. Two facts worth naming
because they postdate the checkpoint carried into this session: UNIT-005 has
merged, so `config/risk.toml` now commits `max_snapshot_age_seconds`,
`daily_loss_stop_fraction`, and `peak_to_valley_fraction`, and D-027 exists.
Neither changes a finding below; both were checked.

## Findings

| # | Severity | Pass | Location | Summary |
|---|---|---|---|---|
| F1 | CRITICAL | Conflict with rules | Scope, lines 46-48, 62-64 | `Exiting` has exactly one legal transition in the named diagram, and Scope forbids adding any other. A fail-closed halt or an escalated flatten failure while exiting has nowhere to go. |
| F2 | CRITICAL | Unfalsifiable criteria | Success criteria, lines 117-120 | Criterion 9's own observation is not available under this feature's control, and the spec never says what "done" means while it stays unmet. |
| F3 | HIGH | Coverage | Outcome line 29; Constraints line 83 | Manual and emergency flatten are promised and bound by rule bullet 8, and no success criterion falsifies either. |
| F4 | HIGH | Underspecification | Success criteria, lines 101-102 | "Impossible, not merely refused" names no mechanism, and the one merged function that reaches the transport takes no arm parameter at all. |
| F5 | HIGH | Unfalsifiable criteria / Coverage | Constraints, lines 87-91 | The `Literal[False]` typing is described as the mechanism that stops a redirect replay. A type annotation cannot enforce an implementation's runtime behaviour, and no criterion tests the new transport's actual behaviour on a 3xx. |
| F6 | HIGH | Coverage | Outcome lines 33-35 | "Killing the process at any point" is broader than what criteria 7 and 8 cover; neither falsifies the session's own state (Ready/Working/Open/Exiting/Halted) being reconstructed wrong after a restart when the order state is not ambiguous. |
| F7 | MEDIUM | Consistency | Scope, lines 62-64 | Design section 11 contains one diagram, not two. The per-order machine's eleven states come from `.claude/rules/30-execution.md` bullet 4, not from section 11. |
| F8 | MEDIUM | Consistency | Constraints, lines 79-83 | "Bullet 2 / Bullet 5 / Bullet 8" does not say which of the two named files each belongs to. All three are in `30-execution.md`; `01-safety.md`'s own bullet 2 is about secrets, not arming. |
| F9 | MEDIUM | Underspecification | Open questions, lines 139-147 | The arm-interface marker bundles a UX decision with a numeric threshold that D-017 says cannot be invented in code. The two need different resolution mechanisms. |

## Detail

### F1, CRITICAL: the diagram's only escape hatch is missing from Exiting

Scope (lines 46-48) binds the orchestrator to "the transitions that diagram
[section 11] names and no others." The diagram itself:

```
Disarmed --> Ready: arm paper configuration
Ready --> Working: approved entry submitted
Working --> Open: complete fill reconciled
Working --> Ready: cancel or reject
Open --> Exiting: exit trigger
Exiting --> Closed: flat and reconciled
Closed --> Ready
Ready --> Halted: health or risk breach
Working --> Halted: uncertainty or breach
Open --> Halted: kill switch
```

`Exiting` has exactly one outgoing edge: to `Closed`, on success. There is no
`Exiting -> Halted`. `.claude/rules/01-safety.md` bullet 4 requires that "any
uncertainty about endpoint, account, clock, quote freshness, feed, position
state, order state, model/config hash, or risk state produces a fail-closed
halt", with no stated exception for the exiting leg, and
`.claude/rules/30-execution.md` bullet 8 requires that "emergency flatten is
observable and idempotent; failure escalates and keeps entry disabled." The
Assumptions section (line 163) itself places flatten completion reporting in
UNIT-017, which is titled to report exactly this: "Evaluate the equity kill
switch and report flatten completion." So the merged code this feature calls
into already produces a failure signal for exactly the moment the diagram
gives the orchestrator nowhere to take it.

Read literally, as Scope's "and no others" instructs, an implementer cannot
build the one thing both cited rules require here: a halt reachable from
`Exiting`. Read loosely, the implementer adds the edge and Scope's own clause
is false. Either the spec changes (the diagram gains the edge, and the
question moves to whether that is a change to section 11 or a documented
addition local to this feature) or the decision is surfaced as its own
`[NEEDS CLARIFICATION]`, the way the other three open questions are. This is
not a hypothetical: it is the highest-risk moment in the whole lifecycle, an
in-flight position with a losing flatten attempt, and it is the one moment the
scoped machine cannot represent.

The same absence also answers part of the question about criterion 5. Outcome
(line 29) promises disarm "available at any time," and after the initial
`[*] --> Disarmed`, the diagram has no transition back to `Disarmed` from any
state. If disarm is understood as its own labelled state re-entry, criterion 5
has no target scoped for it either; if disarm is understood as revoking the
arm token independent of the diagrammed state, that reading survives, but
`Exiting -> Halted`'s absence does not, because `Halted` already exists and is
reachable from three of four other operating states, deliberately, so its
absence from the fourth is not an oversight in the same forgiving way.

### F2, CRITICAL: criterion 9 has no observation available to this feature

Criterion 9 (lines 117-120) requires "the exact commands and their output
recorded" against a real paper account, and states in the same sentence that
it "cannot be satisfied before G0." Scope (lines 71-72) places G0 itself out
of scope: "This feature can be built and tested against doubles without it,
and cannot be believed without it." `project-state/STATUS.md`'s "Next three
tasks" places G0 ownership with `mazwy`, with a credentialed call already
returning 401 and no date recorded anywhere for when access clears.

Applying the pass's own test: name the observation that would falsify
criterion 9, then ask whether it is physically available at the point the
criterion applies. It is not, and not for a timing reason inside this
feature's control the way UNIT-010's redirect example was; it is blocked on an
external, undated gate this spec explicitly excludes from its own scope. The
nine other criteria remain independently falsifiable and this finding does not
spread to them. But the spec never says what completion means while criterion
9 stays open: whether the other nine passing constitutes this feature being
done, with criterion 9 tracked as a separate G1 gate against a later date, or
whether the feature is not "done" until criterion 9 clears, in which case it
has no path to being called done on any date currently in this project's
control. One line settling that would remove the ambiguity; right now a plan
built from this spec has no answer to give a reader who asks when the feature
is finished.

### F3, HIGH: flatten is promised and bound by rule, and untested by any criterion

Outcome (line 29) promises "manual flatten remain[s] available at any time."
Constraints (line 83) cites rule bullet 8 by name: emergency flatten must be
"observable and idempotent," must escalate on failure, must keep entry
disabled on failure, and must never be presented as guaranteed liquidation.
`.claude/rules/30-execution.md`'s own test list separately names "flatten
failure" as one of the required test scenarios, alongside duplicate
invocation, ambiguous submit, and the others this spec's other nine criteria
do cover.

None of the ten success criteria mentions flatten. Criterion 9 comes closest
("cancel or fill, reconcile, and exit") but that is the happy-path G1 lifecycle
against a live account, not a test of what happens when a flatten attempt
fails, which is the scenario the cited rule and the cited rule's own required
test list are actually about. As written, all ten criteria could pass while
flatten-failure escalation is entirely unbuilt and untested, which would
satisfy this spec while violating a rule the spec itself names as
non-negotiable.

### F4, HIGH: "impossible, not merely refused" has no stated mechanism

Criterion 3 (lines 101-102) deliberately echoes UNIT-012's own review finding,
whose language this criterion borrows almost exactly: a safety property must
be a structural impossibility, not a caller's diligence. But the merged
function that actually reaches the transport,
`send_paper_request(configuration, path, body, transport, recorder)` in
`src/alphaledger/broker/endpoint.py`, takes no arm parameter of any kind, and
Scope (lines 59-61) forbids changing it. So "impossible" cannot be a property
of that function's own signature; it can only be a property of whatever this
feature builds around it, and that only holds if every legitimate call site is
funnelled through the new gate, which is an architectural convention this
project already relies on elsewhere (AGENTS.md: "the application order adapter
is the only order path") but does not enforce with the type system anywhere
that exists today.

Two competent implementers read this differently. One builds a thin
`if not armed: raise` guard immediately before calling
`send_paper_request`, which is precisely the "merely refused" shape the
criterion's own wording rules out, and it would pass every test naively
written against it. The other builds a submission entry point that requires a
typed arm token constructible only by the arm action, so that no caller can
even express a call without one, closer to what "impossible" means elsewhere
in this codebase (UNIT-012's `RecordedSubmissionAttempt`, mentioned by name in
its own handoff notes, is exactly this pattern applied to a different safety
property). The spec should name which of these it means, the way UNIT-012's
own intake eventually had to.

### F5, HIGH: the redirect typing is described as enforcing more than typing can

Constraints (lines 87-91): "`follow_redirects` as `Literal[False]`... an
implementation must not acquire the ability. This is shape, not preference,
and it is the mechanism that stops a redirect replaying an order against
another host."

Checked directly against `src/alphaledger/broker/endpoint.py`. The Protocol's
`Literal[False]` constrains what a caller may pass at a typed call site; it
does not and cannot constrain what a conforming implementation does inside its
own method body. A transport class can declare
`def request(self, url, body, *, follow_redirects: Literal[False]) -> TransportResponse`
and still configure its underlying HTTP client to follow redirects regardless
of the argument's value, and mypy has no way to see into that body and object.
The actual runtime defence already merged is
`send_paper_request` always calling with `follow_redirects=False` explicitly,
and `_assert_safe_redirect` rejecting any 3xx whose target is not the paper
origin, both of which operate on the response the transport returns, which
means they defend correctly only if the transport itself does not silently
chase the redirect before returning. Nothing in scope establishes that the new
transport will not.

This matters because it is exactly the failure this rule set exists to
prevent: a redirect replaying a request against a non-paper host. The
Constraints section should say the true mechanism (the runtime response check
plus the explicit argument at the one call site, not the type alone), and
Success Criteria has no line that would falsify a transport implementation
that silently followed a redirect internally. One is needed: something like "a
transport that internally follows a redirect is rejected by a test that
injects one and asserts the response, not a chased final response, is what
`send_paper_request` receives."

### F6, HIGH: session-level restart fidelity is under-covered

Outcome (lines 33-35): "Killing the process at any point and restarting it
produces a system that agrees with the broker about what exists, and that
refuses new entries until it does." That is a claim about the session's own
position in its seven-state machine, not only about one order's identity.

Criterion 7 falsifies a narrower thing: two broker orders sharing one derived
client order id, which is per-order idempotency, already the exact shape of
UNIT-012's own restart tests. Criterion 8 falsifies a different narrower
thing: a new entry accepted while an order's state is unknown. Neither
falsifies a session that restarts into the wrong one of `Ready`, `Working`,
`Open`, `Exiting`, or `Halted` when the order state is not ambiguous at all,
for example a fully reconciled `Open` position after a restart that resumes
into `Ready` and arms a second, concurrent entry against an already-open
position it never lost track of at the per-order level. That failure mode
would pass criteria 6, 7, and 8 as currently worded, and it would still
directly contradict the Outcome line above and the "resuming from broker truth
and the ledger rather than from memory" line in Scope (line 55).

### F7, MEDIUM: section 11 does not show two diagrams

Scope (lines 62-64): "The per-order state machine, which is merged as
UNIT-012 and is a different scope from the session machine. Design section 11
shows both and they are not the same diagram."

Read directly against `options-alpha-agent-design.md` section 11: it contains
one `mermaid` diagram, the seven-state session and arm machine. The eleven
states of the per-order machine (`proposed`, `rejected`, `submitted`,
`working`, `partial`, `filled`, `cancel_pending`, `canceled`, `expired`,
`closing`, `reconciled`) are not drawn anywhere in section 11; they are listed
in `.claude/rules/30-execution.md` bullet 4, and `specs/units/012-order-state-
machine.md`'s own "Two different machines" section cites the rule file for
them and section 11 only for the session machine. The underlying claim, that
the two machines are separate scopes and UNIT-012 already says so, is
verified true. The citation of where the second machine is drawn is not.

### F8, MEDIUM: an unattributed bullet number across two files

Constraints (lines 79-83) names both `.claude/rules/01-safety.md` and
`.claude/rules/30-execution.md` in one sentence, then says "Bullet 2...
Bullet 5... Bullet 8" without saying which file each belongs to. Checked
against both files directly: all three numbers refer to
`.claude/rules/30-execution.md`. `01-safety.md`'s own bullet 2 is "treat
`.env`... as sensitive," unrelated to arming. A reader who does not open both
files could misattribute the citation; the fix is naming the file per bullet.

### F9, MEDIUM: the arm-interface marker bundles two different questions

The marker at lines 139-147 asks two things in one paragraph: what mechanism a
human uses to arm (a UX and architecture question, answerable in a
`spec-clarify` conversation), and how long an arm lasts (a numeric threshold
that D-017 says "may not be invented in code," meaning it needs a committed
`config/` value and a decision record, the same shape UNIT-005 just closed for
three other risk thresholds). The first resolves by picking an answer; the
second resolves by adding a value to `config/risk.toml` and recording why, not
by picking one in conversation. Leaving them as one marker risks
`spec-clarify` answering the mechanism question and treating the duration as
settled by the same conversation, when D-017's own rule says it cannot be.

## Six passes, stated plainly

- **Ambiguity**: no finding. No load-bearing adjective (fast, robust, secure,
  reliable, appropriate, correct, and similar) appears in the spec text
  undefined by a numbered criterion.
- **Unfalsifiable criteria**: F2 and F5. All ten criteria were read against
  the standard: name the falsifying observation, ask whether it is available
  where the criterion applies. Criteria 1, 2, 4, 6, 8, and 10 pass this test
  cleanly. Criterion 7 also passes; it is the closest match to UNIT-012's
  already-merged restart handling and does not have the defect this pass looks
  for. Criteria 3 and 9 do not, for different reasons: criterion 3's
  observation is available but the mechanism that would produce it is
  unnamed and contested by scope (F4, filed under underspecification because
  the two readings differ rather than the observation being unavailable);
  criterion 9's observation is genuinely unavailable under this feature's own
  control (F2).
- **Underspecification**: F4 and F9.
- **Conflict with the project's own rules**: F1 and F3.
- **Coverage**: F3 and F6. Every other Scope-In line traces to at least one
  criterion: the transport to criteria 1, 2, and 10; the arm and its expiry to
  3, 4, and 5; the ledger to 6; restart-of-the-order to 7; refusing entries on
  unknown state to 8; the G1 lifecycle to 9. Every criterion traces to
  something in Scope. The two gaps are outcomes with nothing behind them, not
  criteria with nothing behind them.
- **Consistency**: F7 and F8. Terminology (arm, disarm, session, orchestrator,
  transport, ledger, reconcile, halt) is stable throughout and does not drift
  between sections.

## Fitness to plan

Two CRITICAL findings, four HIGH, three MEDIUM. **Not fit to plan from.**

The single most serious thing found is F1: Scope's own restriction, "the
transitions that diagram names and no others," forbids the one transition
(`Exiting -> Halted`) that this spec's own cited rules require to exist, at
the exact moment in the lifecycle where a halt matters most, an in-flight
exit that is failing. That is not an aspirational gap; it is a scope clause
and a safety rule the same spec cites, pointing in opposite directions.

On the three criteria flagged for closer reading: criterion 5 was a good
instinct, though the defect it traces to lives in Scope's transition
restriction rather than in criterion 5's own wording, and it is reported as
part of F1. Criterion 3 was also a real find, filed as F4. Criterion 7 was
not weak; it already matches UNIT-012's merged restart handling closely and
no defect was found in it. The fourth, unflagged criterion with the same
class of problem is 9, filed as F2, and it is graded CRITICAL rather than
HIGH because the observation it names is not available anywhere under this
feature's control, not merely contested between two readings.

Recommended next step: run `spec-clarify` on F1, F2, F3, F4, F5, and F9 before
`spec-plan`. F6, F7, and F8 do not block clarification and can be corrected
alongside it.

## Second pass, 2026-08-31

Read-only pass over `specs/features/001-autonomous-session/spec.md` after
`spec-clarify` answered three `[NEEDS CLARIFICATION]` markers (now the
`## Clarifications` section) and the spec's own author edited the rest of the
document to address F1 through F9. Verified against the working tree at
`develop` at `1f732ac`, the same ref the first pass read; the feature
directory itself is untracked, so the ref identifies the code the spec is
read against, not the spec text. `src/alphaledger/broker/endpoint.py` was read
directly again, and `alpaca-py` 0.44.0's actual source was read from the `uv`
cache to check the transport-split clarification against the library it
names, not against a description of it.

### F1 through F9, resolution

| # | Status | Settling text |
|---|---|---|
| F1 | RESOLVED | Scope now states the two added edges by name and cites the conflicting rule for each: "`Exiting` has exactly one outgoing edge there, to `Closed` on success... `Exiting -> Halted` is therefore required" and "A disarm edge from every non terminal state is therefore required" (lines 56-69), naming both as deliberate deviations from the diagram rather than silent ones (lines 71-73). |
| F2 | RESOLVED | Criterion 9 no longer needs a live account: "against a recorded fake broker that replays real Alpaca response shapes... This is what done means for this feature, and it does not wait on G0" (lines 152-156). Criterion 9a carries the live-account sequence explicitly out of this feature's own definition of done: "This is the G1 gate criterion, not a criterion of this feature" (lines 157-162). |
| F3 | PARTIALLY RESOLVED | Criterion 13 gives flatten and halt a falsifiable line for the first time: "available while armed and take effect without waiting for the next scan... Falsified by either being reachable only between invocations" (lines 175-178), and Scope's F1 fix makes a failed flatten representable in the state machine at all (`Exiting -> Halted`). But no criterion falsifies the specific behaviour `.claude/rules/30-execution.md` bullet 8 and its own required test list actually name: a flatten attempt that fails escalates and keeps entry disabled. Criterion 13 tests availability and timing, not outcome on failure. See N2 below for a sharper problem the same criterion introduces. |
| F4 | STILL OPEN | Criterion 3's text is byte-for-byte unchanged: "Submitting without a valid arm is impossible, not merely refused. Falsified by any code path that reaches the transport with no arm state present" (lines 130-131). Nothing elsewhere in Scope, Constraints, or Clarifications names a mechanism (a typed arm token, a submission entry point that cannot be called without one, or anything else) that would make "impossible" a structural property rather than a guard clause. Grepped for `token`, `construct`, and `impossible` across the whole file: the only hits are the phrase itself and unrelated uses of "construction" in the read-client and reconstruction discussions. This was claimed fixed and was not. |
| F5 | RESOLVED | Constraints now states the true mechanism instead of the typing: "that typing constrains callers at type check time and constrains nothing about what an implementation's body does at run time. The implementation must therefore be tested for the behaviour, not assumed to have it, which is criterion 12" (lines 115-120). Criterion 12 supplies the missing test: "Falsified by a stubbed server answering 3xx with a Location the transport then requests. The Protocol's typing does not establish this; only the test does" (lines 172-174). |
| F6 | RESOLVED | Criterion 14 is new and broader than 7 and 8: "reconstructs to a state that agrees with broker truth, or refuses to trade and says which fact it could not establish. Falsified by a reconstruction that silently differs from the broker in any order or position, not only in the ambiguous submit case criterion 7 covers" (lines 179-183). This is exactly the restart-into-`Ready`-with-a-live-`Open`-position failure mode F6 named. |
| F7 | RESOLVED | Scope now attributes the per-order states correctly: "Section 11 carries the session diagram; the eleven per-order states come from `.claude/rules/30-execution.md` bullet 4" (lines 90-92), and no longer claims section 11 draws two diagrams. |
| F8 | STILL OPEN | Constraints still reads: "`.claude/rules/01-safety.md` and `.claude/rules/30-execution.md`. Bullet 2 requires... Bullet 5 makes... Bullet 8 forbids..." (lines 107-111), with no file attributed to any of the three numbers. Checked again directly: all three are in `30-execution.md`; `01-safety.md` bullet 2 is the secrets-handling bullet, unrelated. The very same paragraph that fixed F7 (lines 90-92) shows the pattern that would have fixed this: name the file per bullet, the way lines 59-61 already do for the two safety-rule citations inside Scope. This was claimed fixed and was not. |
| F9 | RESOLVED | The Clarifications entry on arming (lines 248-268) answers the mechanism question in conversation (the two-step hash display and confirm) and answers the duration question by committing a value instead: "the arm's maximum lifetime is a committed value in `config/risk.toml`, hashed with everything else, not a constant in code and not a caller supplied parameter" (lines 263-265), citing D-017 and UNIT-005 exactly as F9 recommended. |

Six of nine are genuinely resolved: F1, F2, F5, F6, F7, F9. F3 is real but
partial. F4 and F8 are not fixed at all, and F4 is the more consequential of
the two: it is the same "impossible, not merely refused" gap that made
UNIT-012 take a review round to close on a materially similar property, and
nothing about this pass shows the author even attempted the edit.

### New findings from the three clarified decisions

| # | Severity | Location | Summary |
|---|---|---|---|
| N1 | CRITICAL | Scope line 49, Clarifications lines 207-226 | The read client's own named library reintroduces the exact hazard `.claude/rules/01-safety.md` forbids adding. |
| N2 | CRITICAL | Success criteria, lines 175-178 | Criterion 13 requires flatten and halt to act "without waiting for the next scan," but nothing establishes an invocation path that is not the scan schedule. |
| N3 | CRITICAL | Assumptions, lines 194-197; design section 15 | Section 15's "config hash changes after arm -> disarm and require re-arm" is asserted as an outcome and tested by no criterion. |
| N4 | HIGH | Scope line 49, Clarifications line 211 | `alpaca-py`'s `TradingClient`, the class the applicable to a standard trading account, has no account-activities method. |
| N5 | HIGH | Success criteria, line 140 | Criterion 5's "no in-flight exception" names no recheck mechanism, the same defect class as F4. |
| N6 | MEDIUM | Success criteria, lines 165-171 | Criterion 11's "narrowed by construction" names no concrete shape for the read-client wrapper. |
| N7 | MEDIUM | Scope line 49; `pyproject.toml` | `alpaca-py` is not a committed dependency anywhere in the tree today. |

#### N1, CRITICAL: the read client's own library reintroduces the forbidden switch

Checked directly against the installed `alpaca-py` 0.44.0 source (the same
version D-012 verified resolves on cp314), not against its documentation.
`alpaca.trading.client.TradingClient`, the one class in the library that
exposes `get_account`, `get_clock`, and `get_all_positions`, the exact reads
Scope line 49 and Clarifications line 211 assign to it, is constructed as:

```python
def __init__(self, api_key=None, secret_key=None, ..., paper: bool = True, ...):
    ...
    base_url=(url_override if url_override else BaseURL.TRADING_PAPER if paper else BaseURL.TRADING_LIVE)
```

`alpaca.common.enums.BaseURL.TRADING_LIVE` is the literal string
`"https://api.alpaca.markets"`. `.claude/rules/01-safety.md` states, in full:
"Paper trading is a compile-time and runtime boundary. Never add a live host,
live credential path, or generic `paper=false` switch." `paper: bool = True`
is precisely that switch, sitting in the constructor of a class this feature's
own Clarifications commit to depending on and instantiating. AGENTS.md's
non-negotiable boundary and D-001 say the same thing in different words:
there is no live-mode path anywhere in this project.

This is not hypothetical or contingent on a bug. `src/alphaledger/broker/
endpoint.py` exists because the write path needed exactly this defended:
`EndpointConfiguration.from_resolver`, `assert_paper_endpoint`, and
`resolve_paper_base_url` all exist to make the live host unreachable by
construction on that path. Nothing in Scope, Constraints, or the Clarifications
names an equivalent assertion for the read client's own `TradingClient`
instantiation. Criterion 1 ("No live host string, live credential path, or
mode switch exists anywhere in the feature") is written broadly enough to
cover this, but nothing currently forces the call site that constructs the
read client to be tested the way `endpoint.py`'s own tests presumably test the
write path, and the call site itself, wherever it is written, will contain the
literal token `paper=True`, a mode switch by the rule's own definition, whether
or not it is ever set to `False`. The spec should either name the required
runtime assertion (read the resulting client's resolved base URL back and
compare it to the paper host, the same discipline `assert_paper_endpoint`
already applies to the write path) as part of Scope, or add a success
criterion that a test constructing the read client with a tampered `paper=False`
or a live `APCA_API_BASE_URL` fails closed, mirroring criterion 1's own test.
As written, the criterion exists; the mechanism that would let anything satisfy
it for this new client does not.

#### N2, CRITICAL: criterion 13 names no invocation that is not the scan schedule

Design section 4's cadence is explicit and exhaustive: "Scheduled scans:
approximately 10:00, 12:30, and 15:00 ET. Event rescan: only on a newly
observed, eligible Alpaca news item." The Clarifications' own answer on the
orchestrator shape says invocations are "scheduled" throughout (lines 228-237)
and every other use of the word "invocation" in the spec pairs it with
"scheduled" (lines 33, 82, 230). Grepped the whole file for "on demand,"
"CLI," "trigger," and "command": none of those appear.

Criterion 13 requires manual flatten and emergency halt to "take effect
without waiting for the next scan" (lines 175-178), falsified by either being
"reachable only between invocations." Applying the pass's own test: is the
falsifying observation available? Under the described architecture, in which
nothing runs except at a scheduled scan, an event rescan, or (implicitly) the
two-step arm/disarm action, the next opportunity for any code to run at all,
including flatten, genuinely is the next scan, unless flatten and disarm are
themselves a fourth, unscheduled kind of invocation that a human can start at
any moment. Arm and disarm almost certainly are exactly that already, since a
"two-step human arm action" cannot itself wait for a 10:00 scan to begin. But
the spec never says this generalises to flatten and halt, and Scope's own list
of what the orchestrator does ("scan, decide, approve, submit, reconcile, exit,
and halt," lines 78-80) reads as one sequence belonging to one invocation kind,
not as a set of independently triggerable entry points. Two competent
implementers diverge here: one builds flatten as a parameter to the same
scheduled scan function, which satisfies Scope's literal text and fails
criterion 13 outright; the other builds it as a standalone command a human runs
at any time, which is almost certainly what was intended and is not what is
written. This is the "success criterion that cannot be observed" case the
pass's severity rubric names CRITICAL directly, and it is exactly the shape the
task's own framing anticipated.

#### N3, CRITICAL: section 15's re-arm-on-drift rule has no criterion and no stated mechanism

Design section 15's failure table states plainly: "Risk/data/config hash
changes after arm | Disarm and require explicit re-arm." The Assumptions
section asserts this happens: "The arm binds to the frozen configuration hash
UNIT-004 computes, so editing a committed threshold during a session
invalidates the arm rather than silently changing the rules under it" (lines
194-197). But "binds to" only describes what the arm record stores at the
moment it is created; it says nothing about anything re-checking that binding
later. The Clarifications' own "configuration drift" fix (lines 257-261) closes
a narrower window than the one Assumptions claims: it makes a hash supplied at
the confirm step fail to match if the config changed between display and
confirm, which is entirely before an arm exists. It does not describe any check
that runs during an already-armed session, invocation after invocation, to
compare the arm record's bound hash against the currently committed
configuration and disarm on a mismatch. No success criterion tests this. As
written, an implementation that arms once, stores the hash, and never reads
`config/risk.toml` again until the next arm would satisfy every one of the
fourteen criteria while silently violating the one behaviour section 15 states
outright, and Assumptions asserts as though it already holds. This is the same
error pattern F2 found in the first pass, a claim stated as fact with nothing
in Scope or Success Criteria that would make it false if it were not built.

#### N4, HIGH: the read client's own library has no activity-read method

Checked against `alpaca-py` 0.44.0's actual method list.
`alpaca.trading.client.TradingClient`, the class applicable to a standard
paper trading account, exposes `get_account`, `get_clock`,
`get_all_positions`, `get_open_position`, and over a dozen others, none of
them an account-activities read. `get_account_activities` exists only on
`alpaca.broker.client.BrokerClient`, which is a different Alpaca product (the
Broker API, for a platform managing other people's brokerage accounts,
authenticated with broker API credentials this project does not have and
should not acquire). Scope line 49 and Clarifications line 211 both list
"activity" or "activities" as part of what the `alpaca-py` read client covers,
alongside account, position, and clock. `.claude/rules/30-execution.md` bullet
5 requires reconciling "orders, activities, and positions" on startup and on a
schedule, so this is not a cosmetic omission; it is one of the three things
reconciliation is required to read. Either the spec is wrong about `alpaca-py`
supplying activity reads and that data has to come from a third path (a raw
HTTP GET that is neither the order-write transport nor the SDK-backed read
client), or "activity" should be dropped from the read-client's stated scope.
Either way, the clean two-way split the Clarifications describe ("`alpaca-py`
for reads... raw HTTP... for anything that places, cancels, or replaces")
understates what actually has three parts once activity reads are accounted
for.

#### N5, HIGH: criterion 5 has the same unnamed-mechanism defect as F4

Criterion 5: "Disarm takes effect before the next submission, with no
in-flight exception. Falsified by an order submitted after a disarm returned"
(line 140). Under the scheduled-invocation architecture, a disarm written by a
separate, concurrent action (arm/disarm's own on-demand invocation, per N2)
while a scan invocation is already mid-flight can only be caught if that
invocation re-reads the arm record immediately before firing the transport
call, not merely once at the top of the invocation. `.claude/rules/
30-execution.md` bullet 1 requires exactly this discipline for the endpoint
itself: "Assert the exact paper host at process start and immediately before
submit." No equivalent sentence exists anywhere for the arm state. Two
competent implementers diverge exactly as F4 describes: one checks the arm
once per invocation (fails the race), the other rechecks immediately before
the transport call (passes it). This is not necessarily CRITICAL, since the
observation criterion 5 names is available and the mechanism that would
satisfy it is a straightforward extension of a pattern this codebase already
uses elsewhere; it is the same class of underspecification F4 already names,
recurring on a second criterion.

#### N6, MEDIUM: "narrowed by construction" still names no shape

Criterion 11 and Clarifications lines 221-226 both say the read client must be
"narrowed by construction, not by convention" but neither states what that
construction is: a private `TradingClient` instance never exposed to a caller,
and application-level return types that do not pass an SDK model instance
through unexamined, in case a future `alpaca-py` release attaches a bound
method to one. D-021 rejected the WHAT/HOW split generally on the grounds that
this project's invariants are type-shaped and the HOW is often the entire
point (its own example being UNIT-010's "no `paper: bool`" requirement, which
N1 shows is exactly the property at stake here too). The same reasoning
applies: "by construction" is asserted, not specified.

#### N7, MEDIUM: `alpaca-py` is not yet a dependency anywhere in the tree

`pyproject.toml`'s `dependencies` list currently reads `numpy==2.5.2` and
`scikit-learn==1.9.0` only, added by D-027 for UNIT-025. `alpaca-py` appears
nowhere in `pyproject.toml` or `uv.lock`. This is not a defect in the spec's
reasoning, but the Scope and Clarifications commit to a library that does not
exist in the dependency set yet, without naming the D-027-style consequence
(a widened path glob onto `pyproject.toml` and `uv.lock`, and the D-010
tension D-027 itself recorded and called "not a precedent"). A plan built from
this spec needs to decide, explicitly, which unit adds this dependency and
under what glob, or repeat the improvisation D-027 already flagged as
one-time-only.

### Ambiguity, coverage, and consistency over the expanded criteria set

Re-ran the ambiguity pass over the full current text (grepped for "robust,"
"appropriate," "reliable," "scalable," "secure," "fast," "simply," "easily"):
no hits, same result as the first pass. Re-ran the unfalsifiable-criteria pass
against all sixteen numbered items, 1 through 14 plus 4a and 9a. 4a is
falsifiable as stated (an arm attempted without the hash, or after an edited
config, are both observable at test time). 9a is deliberately not a criterion
of this feature and says so; it is a boundary marker, not a target, and grading
it for falsifiability the way 1 through 14 are graded would be applying the
wrong test to it. 11, 12, and 14 are each falsifiable as worded, though 11's
underlying mechanism is unnamed (N6) and its premise about `alpaca-py`'s
surface should also account for N4. 5 and 13 are the two new CRITICAL and HIGH
findings above (N2, N5); 3 is the carried-forward F4. No new consistency
finding beyond F7 and F8: terminology (arm, disarm, session, invocation,
reconciliation) stays stable across the added text.

### Fitness to plan

Six of nine first-pass findings are genuinely resolved: F1, F2, F5, F6, F7,
F9. That is real, checked work, not a claim taken on say-so. F3 is partially
resolved. F4 and F8 were both claimed fixed and are, on direct inspection,
unchanged from the first pass.

This pass: three CRITICAL, two HIGH, two MEDIUM, newly found. Combined with
what survives from the first pass (F4 HIGH, F8 MEDIUM, F3's residual gap
MEDIUM), the spec currently carries three CRITICAL, three HIGH, and four
MEDIUM open findings. **Not fit to plan from.** The CRITICAL count did not
shrink from the first pass; it moved. Two of this round's three CRITICAL
findings, N1 and N2, come directly from the decisions made to close the
first pass's own findings: resolving the transport question (F5, done
correctly) opened a live-host reachability question the first pass never had
occasion to ask (N1), and resolving the invocation-model question opened a
question about whether the flatten/halt criterion the second pass added to fix
F3 can physically be met (N2). The clarify-and-fix cycle traded two settled
CRITICAL findings for two new ones rather than reducing the count, which is
exactly the "an answer sharpens a conflict elsewhere" pattern the assignment
predicted going in.

The single most serious new thing: N1. `alpaca-py`'s `TradingClient` takes a
`paper: bool` constructor argument that resolves to the literal live host
`https://api.alpaca.markets` when false, and the spec's own transport-split
decision commits this feature to depending on that exact class for reads. This
is not a design flaw introduced by this feature's own code; it is a rule
this project wrote for itself, "never add... a generic `paper=false` switch,"
being reintroduced by the one library the spec just chose, with no assertion
anywhere in scope that would catch it if the switch were ever wrong. N2 is the
close second, and the one the task framing already suspected: criterion 13
cannot be met by an implementation that takes Scope's own list of orchestrator
responsibilities literally, and nothing states the on-demand invocation
mechanism that would make it true.

Recommended next step: run `spec-clarify` again on N1, N2, N3, F4, and N5
before `spec-plan`. N4, N6, N7, F8, and F3's residual gap do not block
clarification and can be corrected alongside it.

## Third pass, 2026-08-31

Read-only pass over `specs/features/001-autonomous-session/spec.md` and, for
the first time, `plan.md`, once both existed. Verified against the working
tree on `develop` at `1f732ac`, the same ref the first two passes read;
`git log` and `specs/units/*.md` frontmatter were re-read directly rather than
taken from the checkpoint text, because another agent is working the research
lane concurrently. Confirmed live at read time: UNIT-027 and UNIT-030 are now
`merged`, UNIT-029 is `claimed` by `mazwy/claude`, UNIT-026 and UNIT-028 are
`available`. This matters below, where D-027 turns on whether another unit is
currently open.

### Part 1: the seven claimed fixes, verified against current text

| # | Status | Settling text |
|---|---|---|
| F4 | RESOLVED | Criterion 3 now names a mechanism instead of restating the property: "the submit path takes a value only an arm read can produce, in the shape UNIT-012 already uses for `RecordedSubmissionAttempt`... An `if` guard is not this criterion; a guard can be forgotten at one call site, which is the failure mode the type shape removes" (lines 135-141). That is a real answer to F4's complaint: two competent implementers no longer diverge, because the weaker reading (a guard clause) is now excluded by name. One residue: the edit left the old trailing sentence in place, so the criterion now says "Falsified by" twice, once for the new wording and once for the original (lines 137-138 and 141-142). Cosmetic, not a content defect; noted as T7 below. |
| F8 | RESOLVED | Constraints now attributes every bullet to its file: "`.claude/rules/30-execution.md` bullet 2 requires... its bullet 5 makes... its bullet 8 forbids... `.claude/rules/01-safety.md` bullet 4 requires... and its bullet 1 forbids" (lines 109-116). Checked again directly against both rule files: bullet 2 of `30-execution.md` is the arm-plus-approval-token bullet, bullet 5 is the broker-truth-outranks-local-state bullet, bullet 8 is the flatten bullet; bullet 4 of `01-safety.md` is the fail-closed-halt bullet and bullet 1 is the paper-only bullet. All five attributions are correct. |
| N1 | RESOLVED, verified against installed source | The Clarifications' last entry supersedes the read/write split: "`alpaca-py` is admissible for market data only, where its clients take no paper argument and resolve to a data host that cannot accept an order. Every account, position, activity, and clock read moves onto the merged `PaperTransport` Protocol" (lines 290-293). Checked directly against `alpaca-py` 0.44.0's installed source in the `uv` cache (`~/.cache/uv/archive-v0/4ya8zyx9HQ6z0fE-qC0XW/alpaca`), the same package pass two read from, not from its documentation. `data/historical/stock.py`'s `StockHistoricalDataClient.__init__` takes `sandbox: bool = False`, resolving to `BaseURL.DATA` or `BaseURL.DATA_SANDBOX`; `data/historical/news.py`'s `NewsClient.__init__` takes no host-selection argument at all and is hardcoded to `BaseURL.DATA`. Neither class takes a `paper` argument, and `common/enums.py`'s `BaseURL` shows `DATA`/`DATA_SANDBOX` are distinct literal hosts from `TRADING_PAPER`/`TRADING_LIVE`. Grepped both files and `option.py` for `submit`, `place_order`, `cancel_order`, `replace_order`: none exist anywhere under `alpaca/data/`. The claim survives verification on both halves: no paper argument, and structurally incapable of reaching a trading host or placing an order. |
| N2 | RESOLVED | Criterion 13 now reads "Manual flatten and emergency halt run as their own invocations a human starts at any moment, not as work the scheduled scan performs when it next wakes... an earlier draft of this criterion assumed a running loop that could be interrupted" (lines 190-195), which matches the scheduled-invocation model the Clarifications commit to and matches `plan.md`'s own file layout, where `cli.py` carries `arm, disarm, halt, flatten, scan` as five separate commands rather than flatten and halt being reachable only through `scan`. |
| N3 | RESOLVED | New criterion 4b: "Every invocation recomputes the frozen configuration hash and compares it to the one recorded in the arm. A mismatch disarms and refuses to trade until a human arms again. Falsified by an invocation that trades under a configuration differing from the armed one... an earlier draft asserted the property in Assumptions with nothing building it" (lines 151-156). This is a genuine, falsifiable criterion where none existed, and `plan.md` assigns it: "Criteria 4b, 6, and 14 live here" under UNIT-034 (line 162). |
| N4 | RESOLVED, moot rather than patched | The same superseding Clarification that fixes N1 also removes the problem N4 named: activities no longer come from `alpaca-py`'s `TradingClient` at all (which never had the method), they come from the same `PaperTransport`-backed client that handles orders. `BrokerTruthSource.activities()` in `src/alphaledger/execution/reconcile.py` (already merged) is the interface a new raw-HTTP client satisfies; nothing in the spec or plan still claims `alpaca-py` supplies activity reads. |
| N5 | STILL OPEN | Criterion 5 is unchanged, character for character, from the text pass two quoted: "Disarm takes effect before the next submission, with no in-flight exception. Falsified by an order submitted after a disarm returned" (lines 157-158). Grepped the whole spec for `recheck`, `immediately before`, `race`, `in-flight`, `mid-flight`, and `concurrent`: the only hit is criterion 5's own sentence. No mechanism is named anywhere, the same gap pass two found. This was claimed fixed alongside F4, F8, N1 through N4, and it was not touched. |

Six of the seven are genuinely resolved: F4, F8, N1, N2, N3, N4. N5 is not, and
the claim that it was fixed is false on direct inspection, the same shape of
error pass two caught on F4 and F8 the round before.

F3, not on this pass's verification list but checked for drift since it was
last PARTIALLY RESOLVED: unchanged. Criterion 13 still tests availability and
timing, not outcome-on-failure; no criterion falsifies a flatten attempt that
fails to escalate or that re-enables entry, which is what
`.claude/rules/30-execution.md` bullet 8 and its own required test list name.
Grepped for `escalat` and `entry disabled`: the only hits are in Scope's
already-read F1 fix and Constraints' already-read paraphrase of bullet 8,
neither of which is a criterion. Still PARTIALLY RESOLVED, not regressed.

### Part 2: cross-artifact checks

**Anything the plan adds that the spec never asked for.** Nothing found. The
plan's tool choices (`httpx`, hand-rolled retry, hand-rolled state table,
`argparse`) are implementation decisions inside scope the spec already opened,
not new capabilities. The plan correctly carries forward the spec's final,
superseding decision rather than its superseded one: `broker/client.py` is
described as implementing `PaperTransport` and satisfying
`BrokerOrderLookup`/`BrokerTruthSource`/`PositionSource` all through one raw
HTTP client, with no `alpaca-py` account or position client anywhere in the
file layout. That is the corrected shape from the Clarifications' last entry,
not the superseded read/write split; the plan did not silently regress to the
earlier, wrong version.

**The seventeen success criteria against the five proposed units.**

| Criterion | Unit that would satisfy it | Verdict |
|---|---|---|
| 1 (no live host/credential/mode switch) | 031, trivially also 032-035 since none of them touch the network by the plan's own discriminator | Covered |
| 2 (credential never in a log, ledger, exception, or stack frame) | Not assigned anywhere | **Gap, T2 below** |
| 3 (transport ungateable without an arm read) | 032, explicitly named ("Criterion 3 lives here") | Covered |
| 4 (expired arm blocks submission) | 032, by description ("time limited by a committed threshold") | Covered |
| 4a (hash-confirm arming) | 032, by description ("bound to the frozen configuration hash") | Covered |
| 4b (every invocation rechecks the hash) | 034, explicitly named | Covered |
| 5 (disarm takes effect with no in-flight exception) | Not assigned anywhere | **Gap, see N5 above; the plan compounds rather than closes it, see below** |
| 6 (every transition ledgered) | 034, explicitly named | Covered |
| 7 (restart resolves ambiguity by broker truth) | 034, implicit (sequences UNIT-012's `decide_submission`/`recover_submission`) | Covered |
| 8 (refuse new entries on unknown state) | 034, implicit (sequences UNIT-012's `blocks_new_entries`) | Covered |
| 9 (MLeg lifecycle against a fake broker, commands and output recorded) | Mentioned in Sequencing/Risks, not assigned to a unit or a file | **Gap, T3 below** |
| 9a (same, against the real account) | Explicitly out of this feature's own scope, correctly | N/A by design |
| 10 (tests require no network) | Property of all five units' test suites; no single owner needed | Covered |
| 11 (no `alpaca.trading` import, no live host string) | 031, trivially, since the plan's own "Package before bespoke" rejects `alpaca-py` for this path entirely | Covered |
| 12 (transport does not follow a redirect) | 031, explicitly the class under test in `test_client.py` | Covered |
| 13 (flatten/halt are independent invocations) | 035, by description and by the Sequencing section's own sentence | Covered |
| 14 (restart reconstructs to broker truth or refuses) | 034, explicitly named | Covered |

Two criteria (2, 9) have no owning unit anywhere in the plan, and one (5) is
unfixed at the spec level and also unassigned at the plan level. That is three
of seventeen, not zero, and two of the three are new findings this pass adds
rather than carrying forward.

#### T2, HIGH: criterion 2's redaction boundary is not owned by anything

Criterion 2 requires a credential never reach "a log line, a ledger entry, an
exception message, or a stack frame that is recorded" (spec lines 132-134).
The plan's own architecture puts the client that can raise such an exception
in one unit (031, over `httpx`, talking to a real host and therefore the one
place an auth header or a raw response body could end up inside an exception)
and the code that catches, logs, and records that exception in another (034,
"record" is literally in its one-line description, and criterion 6 already
requires it to ledger every transition). Neither unit's stated scope in
`plan.md` names the boundary between them: nothing says 031's exceptions must
be pre-sanitized before they leave the module, and nothing says 034 must not
serialize a raw exception or traceback object into the ledger without
inspecting it first. This is exactly the shape UNIT-023's news labeler and
UNIT-020's recorder were each held to ("no credential value appears in any
exception message, log line, or repr", UNIT-028's own AC-8, already written
for the research lane's equivalent adapter) but nothing here states it as
either unit's job. Applying the task's own bar: a criterion no unit covers is
a HIGH finding at least.

#### T3, HIGH: criterion 9 asks for an artifact, and no file produces one

Criterion 9 is falsified "by any step that was inspected rather than run"
(spec line 172), and requires "the exact commands and their output recorded"
(line 171). That is a demand for a durable transcript, not only a passing
`pytest` run; UNIT-010's own quality-gate discipline and `scripts/review.sh`
already produce exactly this kind of artifact elsewhere in the project. `plan.md`
discusses the fake broker's fidelity at length in Risks (lines 195-202) and
places the sequence conceptually under UNIT-034 ("034 is one invocation... "),
but no line in File layout (lines 106-121) names a fixture file, a transcript,
or a script that would produce "the exact commands and their output recorded"
as a reviewable artifact. `tests/execution/test_orchestrator.py` proves the
behaviour happened; it does not, by itself, produce the recorded transcript the
criterion's own wording asks for. Either the plan should name where that record
lives (a captured session log checked into the unit's test fixtures, the way
`review.sh`'s own artifacts work) or the criterion should be reworded to ask
only for a passing, network-free integration test. As written, the criterion
exists and nothing in the decomposition owns producing what it asks for.

**Terminology drift.** One instance: the spec says "human" throughout ("a
two-step human arm action," "the human read the specific limits," criterion
13's "a human starts at any moment"). `plan.md` renames the same actor
"operator" three times: UNIT-035 is titled "operator commands," its Needs
column says "a human" but its one-line description calls it "the operator
surface," and Sequencing calls it "the human surface" in one place and implies
"operator" in the unit title. Minor, MEDIUM, filed as T6 below with the other
consistency items.

### Part 3: the decomposition itself

**Disjoint globs, checked by machine, not by eye.** Imported `paths_overlap`
directly from `scripts/coord.py` and ran it over all ten pairs among the five
units' declared paths, taken from `plan.md`'s File layout section:

```python
from coord import paths_overlap
# UNIT-031 vs UNIT-032 .. UNIT-034 vs UNIT-035, ten pairs total
```

All ten pairs returned `False`. The plan's claim that every glob across
UNIT-031 to UNIT-035 is disjoint, and that 031, 032, and 033 can be dispatched
as one batch, holds exactly as stated. Also checked against every currently
open unit's own declared paths (UNIT-026 available, UNIT-028 available,
UNIT-029 claimed by `mazwy/claude`): none of the research-lane paths
(`src/alphaledger/data/**`, `src/alphaledger/forecast/**`,
`src/alphaledger/evidence/**`) reach anything under `src/alphaledger/broker/`,
`src/alphaledger/execution/`, or `src/alphaledger/cli.py`. No cross-lane
collision.

**Nothing amends a merged unit, checked against the actual Protocols.** Read
`src/alphaledger/broker/endpoint.py`, `src/alphaledger/execution/lifecycle.py`,
`src/alphaledger/execution/reconcile.py`, and
`src/alphaledger/execution/killswitch.py` directly. `PaperTransport`
(`endpoint.py`), `BrokerOrderLookup` (`lifecycle.py`), `BrokerTruthSource`
(`reconcile.py`), and `PositionSource` (`killswitch.py`) are all `Protocol`
classes with methods a new class can implement from outside the file; nothing
in any of the four signatures needs to change for `broker/client.py` (031) to
satisfy all four at once. `send_paper_request`'s redirect check
(`_assert_safe_redirect`, `endpoint.py` lines 134-151) already exists and
already operates on whatever `TransportResponse` the new client returns, so
criterion 12 is testable against the new client alone. Criterion 3's gate (an
unforgeable value only an arm read can produce) can be built as a new function
above `send_paper_request`, in 031 or 034, requiring that value as an argument,
without changing `lifecycle.py`'s `decide_submission` signature. The plan's
claim holds for both files named in the task as most likely to need a change.

**The market-data-scope risk the plan flagged on itself: confirmed, graded
without softening.** Read `specs/units/028-alpaca-market-data-adapter.md` in
full. Its Scope explicitly claims "a market-data client behind a small
interface" for exactly bars and news, its Contract names
`alphaledger.data.alpaca.fetch_bars` and `fetch_news`, and its state is
`available`, owned by no one yet, in the research lane. The feature 001 spec's
Scope In independently claims "`alpaca-py`'s market data clients for bars and
news only" (spec lines 52-54) as in scope for this feature. `plan.md`'s own
Risks section names this collision and responds by allocating no market-data
work and no file under `src/alphaledger/data/` to any of 031-035 (plan lines
185-193). That response is the right one given the collision, but it leaves a
new hole neither document closes: the spec's own Scope In still lists that
bullet as in scope for feature 001, no unit in this five-unit decomposition
implements it, and no success criterion tests it either (see the criteria
table above; none of the seventeen references bars, news, or market data). A
scope bullet with zero owning units and zero owning criteria is graded HIGH
here, the same bar the task applies to the seventeen numbered criteria, and it
is not softened for having been the plan's own author who flagged it first;
self-disclosure changes who found it, not what it is. Filed as T4.

**Whether the discriminator actually separates all five units.** `plan.md`'s
Approach section states the rule once: "Nothing but its inputs means a pure
state machine. Durable state but no network means the arm record. The network
but no decisions means the broker client. Sequencing the others and deciding
means the orchestrator. That discriminator puts the four capabilities in four
units with no shared files, which is what makes them dispatchable at once
rather than one after another" (plan lines 18-24). That sentence names four
categories for four units and says they are "dispatchable at once." The
Sequencing section, three paragraphs later, says something narrower and
correct: "031, 032, and 033 have no dependency on each other and can be claimed
and dispatched together... 034 depends on all three... 035 depends on 032...
It is last" (plan lines 166-177). Three things are dispatchable together, not
four, and UNIT-035 never appears in the discriminator paragraph's four
categories at all; its own criterion ("a human") is stated only in the unit
table, not in the prose that is supposed to justify the whole decomposition.
The discriminator does separate all five units from each other in practice, by
file and by dependency, verified above; it just does not say so for the fifth
one, and its own count ("four... dispatchable at once") is wrong by the plan's
later and more careful section. Filed as T5, MEDIUM, an internal
plan-consistency defect rather than a decomposition defect: no two units
collide, the prose describing why is incomplete and briefly self-contradicts.

#### T1, CRITICAL: the plan commits to a dependency it never adds, while another unit is genuinely open

`plan.md`'s "Package before bespoke" section chooses `httpx` for the order and
account path and states: "`httpx`... is already in the resolved set per
D-012" (plan lines 78-79). Checked directly: `pyproject.toml`'s `dependencies`
list is `["numpy==2.5.2", "scikit-learn==1.9.0"]` only; `httpx` appears zero
times in `uv.lock` (`grep -c httpx uv.lock` returns 0) and zero times in
`pyproject.toml`. D-012's verification that the full candidate stack,
including `httpx` 0.28.1, resolves and imports on cp314 was a one-time
interpreter compatibility smoke test in a throwaway environment; it is not a
record that `httpx` is a committed project dependency today, and D-027's own
text confirms this reading: it calls `numpy`/`scikit-learn` "the first runtime
dependency the application carries," a claim that would be false if `httpx`
already counted. No test file in this repository imports `httpx` either
(checked `tests/execution/test_endpoint.py`, the file whose successor
`test_client.py` would need it first).

Building UNIT-031 as `plan.md` describes it therefore requires editing
`pyproject.toml` and `uv.lock`, and `plan.md`'s own File layout section says
the opposite: "Changed: nothing. Every merged file stays as it is" (plan lines
123-124), and UNIT-031's declared paths in the unit boundaries table do not
include either file.

This is not a hypothetical D-010 risk the way it might have read a day
earlier. D-027 records exactly this scenario and names its own boundary: the
prior widening of `pyproject.toml`/`uv.lock` for UNIT-025 "was safe only
because UNIT-025 was the sole claimed unit when the change landed... It is not
a precedent for widening globs onto shared files while other units are open,"
and its revisit clause states the fix outright: "the real risk... is the
answer to it is the separate unit rejected above, not a second widening."
Checked against the registry at read time, not against the stale checkpoint:
UNIT-029 is `claimed` by `mazwy/claude` right now. The condition D-027 warns
about, a second lockfile-touching change landing while another unit is
genuinely open, is not a future risk here; it is the present state of the
repository. A plan that adds `httpx` inside UNIT-031's undeclared globs would
repeat the exact hazard D-027 was written to name, and a plan that adds it
correctly needs a sixth, separate unit that nothing here proposes. Either way,
this is unaddressed, and it directly conflicts with an accepted decision, which
is this pass's bar for CRITICAL.

### T6, MEDIUM: terminology drift, plus one leftover clause

`plan.md` calls the human operator "operator" in UNIT-035's title and its
one-line description, where the spec always says "human." Also filed here:
T7 below is the more substantive half of this pair; this entry is the
terminology note alone. (See "Terminology drift" under Part 2.)

### T7, MEDIUM: a leftover duplicate clause from the F4 edit

Criterion 3's text, after the F4 fix, ends with two falsification sentences
doing the same work: "Falsified by any reachable call to the transport
constructed without one, and by any code path that obtains one other than by
reading a live arm record... Falsified by any code path that reaches the
transport with no arm state present" (spec lines 137-142). The second sentence
is the pre-fix wording, left in place after the first was added rather than
replaced. No content is wrong, but a reader hits the same falsifying
observation stated twice with slightly different words, which is exactly the
kind of drift this pass's consistency check exists to catch. Trivial to fix by
deleting the trailing sentence.

### Fitness to plan

**This pass's new findings:** one CRITICAL (T1), three HIGH (T2, T3, T4), two
MEDIUM (T5, T7; T6 folded into T7's write-up as the same terminology point).
Call it three MEDIUM if T6 and T7 are counted separately by clause rather than
by finding: five items in total this pass beyond the seven-item verification,
one CRITICAL, three HIGH, two MEDIUM.

**Resolved this pass:** 6 of the 7 items sent for verification (F4, F8, N1,
N2, N3, N4). N5 is not resolved and was claimed to be; say this plainly, since
it is the single most useful thing this pass found: **the fix claim for N5 was
false.** It is byte-for-byte the text pass two already read, and nothing
elsewhere in the document supplies the missing mechanism.

**Resolved across all three passes, cumulatively:** 12 of the 16 tracked
findings from the first two passes are now fully resolved (F1, F2, F4, F5, F6,
F7, F8, F9, N1, N2, N3, N4). One is partially resolved and unchanged this pass
(F3). One is open and was twice claimed fixed in effect, once by omission and
once by name (N5, the second time being this session's own claim). Two are
mooted rather than fixed, because the decision that created them no longer
stands (N6, whose "narrowed by construction" concern applied only to the
superseded read-client design; N7, whose missing dependency concern is
superseded by T1's sharper version of the same underlying fact).

**Fit to proceed to `spec-tasks`? No.** A new CRITICAL was found (T1), in the
same pattern as pass two's own N1/N2/N3: resolving old findings correctly
opened a new one rather than only shrinking the count, because the httpx
decision that closes out the transport question (a real improvement) was never
checked against what it costs in `pyproject.toml`. Three HIGH findings sit on
top of it: one previously-claimed fix that was not made (N5, carried forward),
and two criteria this decomposition does not yet own (T2, T3), plus the
market-data-scope conflict the plan named on itself and this pass confirms
rather than waives (T4). Six genuine resolutions this pass is real progress and
should be recorded as such; it does not change the verdict, the same way six
resolutions out of nine did not change it last time. `spec-tasks` should not
run yet.

Recommended next step: resolve T1 first, since it is the one finding that
would actually block a `coord.py claim` or silently violate D-010/D-027 the
moment UNIT-031 is claimed, by either widening UNIT-031's own globs
deliberately (with the D-027 tradeoff named, not silent) or by adding a small,
separate dependency unit ahead of it. Then close N5 and T2 and T3, which are
each a sentence or a criterion away from done, the way N1 through N4 turned out
to be this round. T4 is a spec decision, not a plan defect, and belongs back in
`spec.md`'s own Scope In line, narrowed the way `plan.md` already recommends.

## Fourth pass, 2026-08-31

Narrow, targeted pass. Verify the eight fixes claimed since the third pass and
look for what those fixes broke, rather than re-running all six passes over
the whole document. Read `spec.md` and `plan.md` in full at their current
text, not from the checkpoint. `project-state/DECISIONS.md`'s D-027 was read
in full, not from memory. The registry was read live: `coord.py list` shows
UNIT-029 `claimed` by `mazwy/claude`, UNIT-026 and UNIT-028 `available`,
nothing `in_review`. `specs/units/029-news-labeler-adapter.md` was read in
full, not only its frontmatter, because one of the eight claims turns on what
that unit actually needs. `paths_overlap` was imported directly from
`scripts/coord.py` and run over all pairs among the six units this plan now
names, `UNIT-030b` included, plus UNIT-029; every pair returned `False`.
`pyproject.toml` and `uv.lock` were grepped directly for `httpx`: still zero
hits in both, matching the plan's own claim.

### Part 1: the eight claimed fixes

| # | Claim | Status |
|---|---|---|
| N5 | spec.md criterion 5, a mechanism | PARTIALLY RESOLVED |
| T2 | spec.md criterion 2, the redaction split | PARTIALLY RESOLVED |
| T3 | spec.md criterion 9, the evidence artifact | PARTIALLY RESOLVED |
| T4 | spec.md Scope, no market data | RESOLVED |
| T7 | spec.md criterion 3, duplicate clause | RESOLVED |
| T1 | plan.md, the dependency unit and D-027 | RESOLVED |
| T5 | plan.md, discriminator match | STILL OPEN |
| T6 | plan.md, human versus operator | RESOLVED |

Four resolved, three partially resolved, one still open.

#### N5, PARTIALLY RESOLVED: criterion 5 now names a mechanism, and the plan does not build it

Criterion 5 now reads: "Disarm takes effect before the next submission because
the arm record is read from its durable store immediately before the transport
call, not once per invocation and cached. Falsified by an order submitted
after a disarm returned, and by any submit path that reads the arm earlier
than the call it authorises" (spec.md, lines 163-167).

Judged against the earlier defect directly: two implementers no longer
diverge on wording. One reading, "check once at the top of an invocation," is
now named and excluded by the sentence itself, the same move that fixed F4 and
N5's own sibling criterion 3. This half of the claim is genuine.

But the plan does not assign this mechanism anywhere, and its own text for the
one unit that could own it points the wrong way. `plan.md`'s one line for
UNIT-034 reads: "034 is one invocation: load the arm, verify the configuration
hash, reconcile, rebuild session state from the ledger, decide, act, record,
exit. Criteria 4b, 6, and 14 live here" (plan.md, lines 174-176). "Load the arm"
is the first item in that sequence, read most naturally before "decide" and
"act," which is exactly the "value fetched at invocation start" reading
criterion 5's own sentence rules out. Nothing in UNIT-032's description
("readable as the value the submit path requires," plan.md line 169) says the
read must be repeated immediately before the call that submits, rather than
once when the invocation begins. Criterion 5 is not listed among the criteria
either unit's row claims, unlike 3, 4b, 6, and 14, each of which is named
explicitly against a unit.

This is the same shape T2 and T3 were graded on: a spec fix that supplies a
real mechanism, sitting over a plan that does not name which unit builds it,
and whose own prose for the nearest candidate unit describes the opposite
order of operations. Filed as Q1 below with HIGH severity, since it is a
criterion with no scope behind it, the plan's own severity bar for HIGH.

#### T2, PARTIALLY RESOLVED: the redaction split is real in the spec, silent in the plan

Criterion 2 now reads: "This spans two units, so the boundary is named rather
than left to fall between them: the client raises no exception carrying a
credential, and the orchestrator records no entry carrying one. Both halves
are testable in their own unit, and the sentinel test runs against the
composed path" (spec.md, lines 137-141).

Judged directly: this is a real split, not a restated assertion of coverage.
It names two distinct, independently testable obligations, one per role
("the client," "the orchestrator"), which maps onto UNIT-031 and UNIT-034
without needing to guess. That closes the original complaint, that criterion 2
had no owner and no stated boundary.

What it does not do is reach `plan.md`. Neither UNIT-031's nor UNIT-034's row
or one-line description mentions criterion 2, the way 032's row names
criterion 3 and 034's own row names 4b, 6, and 14. An implementer reading only
`plan.md`, which is what `spec-tasks` reads to write intakes, would not see
this obligation attached to either unit even though `spec.md` now states it
plainly. Graded PARTIALLY RESOLVED for the same reason as N5: the spec-level
ambiguity is gone, the plan-level ownership line is not yet written.

#### T3, PARTIALLY RESOLVED: the artifact question is closed, the ownership question is not

Criterion 9 now reads: "The evidence is the ledger the run itself writes plus
the test output, not a separate transcript some unit would have to produce...
Falsified by any step that was inspected rather than run" (spec.md, lines
183-187).

Judged for weakening: it is not weakened. The behavioral demand is unchanged,
one MLeg order must actually go through submit, observe, cancel or fill,
reconcile, and exit against a fake broker, and the falsifying observation
("inspected rather than run") is still available and still meaningful. What
changed is which artifact counts as proof, from a transcript nothing in the
decomposition produces to a ledger and test output that UNIT-016 and pytest
already produce as a matter of course. That is a genuine fix, not a
softening.

The ownership question the task asked about directly is not answered.
`plan.md`'s Sequencing section says "Criterion 9 is satisfiable against a
recorded fake broker; criterion 9a is the G1 gate and waits" (plan.md, lines
199-201), naming the criterion but not assigning it to a unit's row the way 3,
4b, 6, and 14 are assigned. No File layout entry names a fixture file for the
fake broker's recorded response shapes. UNIT-034's own row lists "Criteria
4b, 6, and 14 live here" and stops there. The gap T3 found in the third pass,
"no unit owns producing what criterion 9 asks for," has moved from "asks for
an artifact nothing produces" to "asks for an artifact two existing units
already produce, but nothing says which unit's test list actually builds the
fake broker and runs the full lifecycle against it." Narrower than before, and
still open.

#### T4, RESOLVED: no remaining claim to market data anywhere in the spec

Scope now reads: "Nothing under `src/alphaledger/data/`. Market data is
UNIT-028's, and this feature neither fetches bars nor news... An earlier draft
of this Scope listed those clients here, which would have put one capability
under two rows" (spec.md, lines 52-57). Grepped the whole spec file for
"bars" and "news": both appear only inside that sentence and inside criterion
9's "observe" language and the Clarifications' account-read discussion, none
of which claims fetching either. Read the Clarifications section in full,
since it was not rewritten and is where an old claim would most plausibly
survive by omission: its two SDK-related answers discuss account, position,
activity, and clock reads, and end by handing bars and news to UNIT-028 by
name, "UNIT-028 in the research lane will want those same data clients
regardless" (spec.md, line 323). Nothing in Clarifications claims market data
work for this feature. Genuinely resolved.

`plan.md`'s own Risks section did not get the same treatment; see Q2 below.

#### T7, RESOLVED: the duplicate clause is gone

Criterion 3 now ends: "An `if` guard is not this criterion; a guard can be
forgotten at one call site, which is the failure mode the type shape removes"
(spec.md, lines 146-148), with exactly one "Falsified by" sentence earlier in
the same criterion. The second, pre-fix "Falsified by any code path that
reaches the transport with no arm state present" sentence the third pass
quoted is no longer present anywhere in the criterion. Confirmed by reading
the whole numbered item, not by grep alone. Genuinely resolved.

#### T1, RESOLVED: the dependency unit is real, disjoint, and correctly sequenced; the D-027 citation is loose

`plan.md` now names a sixth unit, "UNIT-030b http dependency," owning only
`pyproject.toml` and `uv.lock`, lane `shared`, reviewer `code-reviewer`,
merging first and alone (plan.md, lines 127-136 and 151). Checked mechanically
rather than by eye: `paths_overlap`, imported directly from `scripts/coord.py`,
returns `False` for every pair among UNIT-030b, UNIT-031, UNIT-032, UNIT-033,
UNIT-034, UNIT-035, and UNIT-029 (the one currently claimed unit outside this
decomposition). Twenty-one pairs, twenty-one `False`. `httpx` is still absent
from both `pyproject.toml` and `uv.lock`, matching the plan's own stated fact.
Sequencing is consistent everywhere it appears: the dependency unit first and
alone, then 031, 032, 033 together, then 034, then 035 last.

`lane: shared` and `reviewer: code-reviewer` both have direct precedent.
UNIT-001, UNIT-002, UNIT-003, UNIT-004, and UNIT-005 all declare `lane:
shared` for exactly this kind of foundational, cross-lane unit. Reviewer
choice within that lane already splits on content: UNIT-001, a domain-contract
freeze with real validation logic, uses `code-reviewer`; UNIT-004 and UNIT-005,
which commit actual risk-relevant threshold values, use
`execution-safety-reviewer`. UNIT-030b carries no logic and no threshold, only
a pinned version string, which is closer to UNIT-001's case and further from
UNIT-004/005's. `code-reviewer` is the better fit, not an under-review of a
safety-relevant change; there is no order, risk, reconciliation, or
kill-switch logic in a two-line dependency bump for the reviewer to miss.

Read D-027 in full against the plan's citation, which is the part worth being
careful about. Plan.md says: "That condition does not hold now: UNIT-029 is
claimed by `mazwy/claude` today, so there is a concurrent writer and the
alternative D-027 rejected is the one its own reasoning selects" (plan.md,
lines 132-134). D-027's own text does not say "a concurrent writer exists";
it says the risk is "a second unit needs to change the lockfile while
[the first] is open," and its revisit clause names exactly that scenario as
the trigger for building the separate unit it had just rejected. Checked
directly against UNIT-029's full intake, not only its frontmatter: its own
Scope Out excludes "the concrete, network-calling model client for a specific
provider," so UNIT-029 adds no LLM SDK dependency and needs no change to
`pyproject.toml` or `uv.lock` at all; its declared paths,
`src/alphaledger/evidence/llm_labeler.py` and
`tests/research/test_llm_labeler.py`, confirm it, and `paths_overlap` above
confirms neither file collides with UNIT-030b's. So the specific fact the plan
cites, that UNIT-029 is claimed, is true, but it is not the fact D-027 asks
for, that a concurrent unit needs the lockfile. UNIT-029 does not.

This does not make the decision wrong. A separate, disjoint, mechanically
verified unit is the safer choice regardless of whether UNIT-029 specifically
needs the lockfile, since some future unit might, and the unit costs two
lines. The plan reaches the right place by a citation that overstates what it
checked. Not bent to a false conclusion; loose in its stated reasoning. Filed
as Q3 below, MEDIUM, since the practical outcome is sound and mechanically
confirmed disjoint.

#### T5, STILL OPEN: the two discriminator sentences still disagree, and now say they do not

Approach is unchanged, character for character, from the text the third pass
quoted: "That discriminator puts the four capabilities in four units with no
shared files, which is what makes them dispatchable at once rather than one
after another" (plan.md, lines 22-24). Four categories, four units, all
"dispatchable at once."

Unit boundaries was edited, and now reads: "The discriminator, applied per
function, stated identically to the Approach above so the two cannot drift:
what does this need in order to do its job? Nothing but its inputs, durable
state, the network, the other three, or a human. Five answers, five units"
(plan.md, lines 144-147).

Compared word by word, as asked. Approach names four categories and never
mentions "a human." Unit boundaries names five, adding "a human" for
UNIT-035, and explicitly claims to be "stated identically to the Approach
above." That claim is false on its face: the two sentences name different
counts, four against five, and different category sets. This is the same T5
defect the third pass found, not fixed, and now sharper, because the new
sentence asserts an identity that a direct comparison disproves rather than
silently omitting the fifth unit the way the third pass's read described.
Neither sentence accounts for a sixth category, "the lockfile," for the new
UNIT-030b, even though the table beneath both sentences now lists six units.
Graded STILL OPEN, and the claim to have fixed it is itself inaccurate.

#### T6, RESOLVED: human and operator are now tied together explicitly

UNIT-035's one line reads: "**035** is the operator surface, and operator
means the human who arms" (plan.md, line 177). This does not remove "operator"
from the text, but it closes the drift the third pass found by defining the
term rather than leaving two words for one role unexplained. The Sequencing
section still says "the human surface" once (plan.md, line 196), so both
words remain in the document, but a reader now has an explicit bridge between
them rather than an unexplained switch. Judged as resolved: the defect named
was drift, an unacknowledged inconsistency, not the mere presence of two
synonyms, and the acknowledgement is now there.

### Part 2: what the fixes broke

| # | Severity | Location | Summary |
|---|---|---|---|
| Q1 | HIGH | spec.md criterion 5; plan.md lines 174-176 | Criterion 5's new mechanism is not assigned to any unit, and UNIT-034's own stated sequence, "load the arm" first, reads as the cached-at-invocation-start implementation the criterion now rules out. |
| Q2 | MEDIUM | plan.md lines 206-214 | The Risks section's market-data paragraph is stale: it still says "the spec should be narrowed to match," describing T4 as open, when spec.md has already been narrowed. |
| Q3 | MEDIUM | plan.md lines 132-134; D-027 | The D-027 citation for UNIT-030b treats "a concurrent claim exists" as the condition D-027 names, when D-027 names "a concurrent unit needs the lockfile," and UNIT-029, the cited concurrent unit, does not. The conclusion is still sound and mechanically verified disjoint. |

Q2 is worth stating precisely, since it is a new instance of exactly what this
project's own consistency pass exists to catch. `plan.md`'s Risks section
opens: "**The spec claims market data scope that UNIT-028 already owns.** The
spec's Scope In lists `alpaca-py` market data clients for bars and news...
and the spec should be narrowed to match. It is recorded here rather than
fixed silently, because a plan quietly dropping something the spec asked for
is exactly what the next analysis pass exists to catch, and it should catch
this one" (plan.md, lines 206-214). It caught it, in the sense that T4 is
resolved; but the paragraph announcing the risk was never updated to say so,
so a reader of `plan.md` alone, which is the document `spec-tasks` consumes,
would believe this is still open. The fix landed in the right document and
the stale paragraph was left in the other one.

No new CRITICAL findings this pass. Q1 is the only HIGH.

### Fitness to proceed to `spec-tasks`

Four of eight claimed fixes are genuinely, fully resolved: T4, T7, T1, T6.
Three are partially resolved, real spec-level progress sitting over an
unclaimed plan-level ownership line: N5, T2, T3, and all three share one root
cause, criteria 2, 5, and 9 are none of them named against a unit row the way
3, 4b, 6, and 14 are. One, T5, was claimed fixed and was not; the edit made to
fix it introduced a sentence that asserts an identity between two passages
that, read together, disagree.

**Not yet fit to proceed.** Three items block it directly: T5 is unresolved on
its own terms, and Q1 is a HIGH finding on the same criterion N5 touched.
Unlike the second and third passes, no new CRITICAL surfaced this round; the
pattern of a fix trading one CRITICAL for another has not repeated here. What
has repeated, for the third time now, following F4/F8 in pass two and N5 in
pass three, is a spec-level sentence getting real, careful attention while the
plan-level document that turns it into a unit is not touched to match. That is
not a reasoning defect in any one fix; it is a process gap, spec.md and
plan.md are being edited in separate passes and the second is not being
re-read against the first each time the first changes.

Recommended next step: fix T5 by making Approach's discriminator sentence
name five categories, or six, matching whatever Unit boundaries settles on,
and stop claiming the two are identical unless a direct read confirms it. Add
one line each to UNIT-031, UNIT-032, or UNIT-034's row for criteria 2, 5, and
9, the same way 3, 4b, 6, and 14 already have one, closing N5, T2, and T3 by
assignment rather than by further spec prose, since the spec's own text no
longer needs anything for any of the three. Q2 and Q3 are one paragraph and
one clause respectively and do not block anything on their own. On D-027: not
bent, the separate unit is the right and safe call, mechanically verified; the
sentence citing it should say what was actually checked, UNIT-029's own scope
excludes touching the lockfile, rather than treating any concurrent claim as
sufficient.

## Fifth pass, 2026-08-31

Narrow, targeted pass, run against a claim that four prior fix-verifications
have each turned out to be false at least once (F4/F8 in pass two, N5 in pass
three, T5 in pass four), so this round treats every claimed fix as unproven
until read directly. Read `spec.md` and `plan.md` in full at their current
text. `project-state/DECISIONS.md`'s D-027 was read in full again, not from
this file's own earlier paraphrase of it. The registry was read live:
`coord.py list` shows UNIT-025 `merged`, UNIT-026 and UNIT-028 `available`,
UNIT-029 `claimed` by `mazwy/claude`, nothing `in_review`. `git log` was read
for the UNIT-025 merge and UNIT-029 claim commits specifically, because Q3
turns on which one came first.

### Part 1: the five claimed fixes, verified against current text

| # | Claim | Status |
|---|---|---|
| T5 | plan.md discriminator sentences now agree on six units | RESOLVED |
| Q1 | criterion 5 rewritten to be owned by UNIT-031 | RESOLVED (the assignment holds; see R1 for what it costs) |
| Q3 | D-027 argued from what it says about itself, not a condition it sets for others | PARTIALLY RESOLVED |
| Q2 | Risks' stale "should be narrowed" text | RESOLVED |
| N5/T2/T3 | "Which unit satisfies which criterion" table added, covering all seventeen | RESOLVED (table is real; see R1 and R2 for defects it carries) |

#### T5, RESOLVED: both sentences now say six, and the false-identity claim is gone

Approach: "The lockfile, which is nobody's job and everybody's blocker, means a
dependency unit of its own. Six answers, six units, no shared files, which is
what lets most of them run at once rather than in a queue" (plan.md, lines
23-25).

Unit boundaries: "The discriminator is the one stated in Approach above.
Repeated here in short form only: what does this need in order to do its job?
Its inputs alone, durable state, the network, the other units, an operator, or
the lockfile" (plan.md, lines 152-154).

Compared directly, as asked. Both name six categories in the same order
(inputs, durable state, network, the other units/sequencing, an operator, the
lockfile) and both land on six units. Neither claims the two sentences are
"stated identically" any more; the second is introduced as a short-form
repetition, not an identity claim, and grepping the whole file for "stated
identically" and "four capabilities" returns nothing. The specific defect the
third and fourth passes found, a count mismatch asserted to be an
agreement, is gone. One residual, not a finding: "lets most of them run at
once" is generous, only three of the six (031, 032, 033) actually run
concurrently under the Sequencing section's own account, the other three are
each a solo step in a chain. Noted because it was checked, not filed, since
"most" of six read loosely is not the kind of load-bearing claim this pass's
severity bar reaches.

#### Q1, RESOLVED: criterion 5's assignment to UNIT-031 is the correct call, not a dodge

Criterion 5: "Disarm takes effect before the next submission because the arm
record is read from its durable store immediately before the transport call,
not once per invocation and cached... Falsified by an order submitted after a
disarm returned, and by any submit path that reads the arm earlier than the
call it authorises" (spec.md, lines 163-167).

Judged on the question actually asked: is 031 the right owner, or has the
contradiction just been moved somewhere convenient? The criterion's own text
names the mechanism, read the value immediately before the transport call, and
the transport call is 031's own act, since 031 is "the network" unit
implementing `PaperTransport` over `httpx` (plan.md, Existing surface and
Unit boundaries). Criterion 3's assignment agrees and was not touched this
pass: "032 defines the value, 031 requires it" (plan.md, line 200), and 032's
own one-line description says the value is "readable as the value the submit
path requires" (plan.md, line 170), naming 031, not 034, as the reader. If 034
read the arm and passed a token down to 031, the read would happen at
whatever point 034's own sequence reaches "act", which is exactly the
"cached... at invocation start" shape criterion 5 rules out whenever
reconciliation or a decision step takes any real time in between. Only the
unit that performs the network call can make the read-then-call gap
arbitrarily small by construction. This is judged correct, not a
contradiction relocated to look resolved: 034's own one-liner now says so
explicitly, "It does not load the arm once and carry it; the arm is read at
the call it authorises, which is 031's job and criterion 5" (plan.md, lines
183-185), replacing the literal "load the arm" phrasing the fourth pass
quoted as the anti-pattern.

The assignment is right. It is not free, see R1.

#### Q3, PARTIALLY RESOLVED: the self-referential argument is added and holds; the condition-based argument it was supposed to replace is still there, and still imprecise

Current text: "D-027's revisit condition is a second unit needing to change
the lockfile, not merely a second unit being claimed. UNIT-029 is claimed
today, but its own Scope excludes adding a dependency and its declared paths
never reach `pyproject.toml` or `uv.lock`, so it is not that second unit. The
reason to separate the change is the one D-027 states about itself rather
than a condition it sets for others: it bends D-010, it says so, and it says
it is not a precedent. Repeating a bend that its author labelled unrepeatable
needs a better argument than convenience, and here there is none, because the
change is two lines that block five units and can simply land first"
(plan.md, lines 135-143).

Read D-027 in full again, not from either draft's paraphrase. Its exact
revisit clause: "Revisit only if: a wheel is unavailable on a future
interpreter, or a second unit needs to change the lockfile while UNIT-025 is
open. The second is the real risk and the answer to it is the separate unit
rejected above, not a second widening" (`project-state/DECISIONS.md`, lines
780-783).

The new sentence the claim is about, "The reason to separate the change is
the one D-027 states about itself rather than a condition it sets for
others", is genuine and it holds on direct comparison against D-027's own
text: D-027 does say, about itself, that the UNIT-025 widening "bends D-010"
and "is not a precedent" (`project-state/DECISIONS.md`, lines 774-776), and an
argument from "its own author called this unrepeatable, so repeating it needs
a reason beyond convenience, and there is none here" is sound on its own
terms, independent of whether any particular unit currently triggers the
revisit clause. That argument was not available in the version pass four
read, which argued only from the concurrent-claim misreading, and its
addition is a real improvement.

What was not done is remove the older, condition-based paragraph the new
sentence was supposed to supersede. The paragraph still spends its first half
checking whether UNIT-029 is the "second unit" D-027's revisit clause
describes, and that check is now imprecise in a different way than the
fourth pass found. D-027's clause is scoped to "while UNIT-025 is open," not
to lockfile-touching units in general. Checked against the registry and the
commit history directly: UNIT-025 is `merged` (`coord.py list`), and it
merged at `556bebd`, "chore(registry): mark UNIT-025 merged" (2026-08-30
15:13:21), which is roughly fifty minutes after UNIT-029 was claimed at
`9ac040a` (2026-08-30 14:22:23). So by the time this pass runs, UNIT-025 has
not been an open unit for a full day, and D-027's revisit clause, tied
specifically to UNIT-025's own claim window, cannot be triggered by anything
any more, regardless of what UNIT-029's scope does or does not touch. The
plan's check of "does UNIT-029 need the lockfile" answers a question that is
moot for a more basic reason than the one it states, and neither this draft
nor the fourth pass's own T1 write-up, which first introduced this framing,
noticed that the window had already closed. Rereading that write-up's own
words rather than recalling them: it checks "that UNIT-029 is claimed... it
is not the fact D-027 asks for, that a concurrent unit needs the lockfile.
UNIT-029 does not," and stops there; it never asks whether UNIT-025 itself
was still open, only whether UNIT-029 met the condition. This does not change the
practical conclusion: a separate unit is still correct and still
mechanically verified disjoint, and the added self-referential argument
supports it without needing the revisit clause at all. Graded PARTIALLY
RESOLVED because the claim was "I now argue from X rather than from Y", and
the text argues from both X and a still-imprecise Y, not from X alone.

#### Q2, RESOLVED: the stale paragraph now states its own resolution

Current text: "The spec has since been narrowed to match, so the conflict is
closed; it is left recorded here because the plan flagging a defect in its
own spec, rather than quietly dropping the requirement, is the behaviour
worth keeping" (plan.md, lines 258-261). Grepped the whole file for "should
be narrowed" and "narrowed to match": the only hit is this sentence, and it
now reads as past and closed rather than as an open recommendation. Genuinely
resolved.

#### N5/T2/T3, RESOLVED: the criterion table is real, not decorative

"Which unit satisfies which criterion" (plan.md, lines 191-216) lists
seventeen rows: 1, 2, 3, 4, 4a, 4b, 5, 6, 7, 8, 9, 9a, 10, 11, 12, 13, 14.
Checked against `spec.md`'s own numbered criteria one at a time: those are
exactly the seventeen items the spec carries (fourteen numbered plus 4a, 4b,
and 9a), each appears in the table exactly once, and none is missing or
duplicated.

Checked each row against the owning unit's stated scope for whether that
unit could plausibly deliver it, not only whether a name is present, since a
table that assigns everything and means nothing was the thing to guard
against. Fourteen of seventeen rows hold up cleanly against the unit
descriptions elsewhere in the same document: 1 (030b adds no live-host string,
031 is the only network path, the rest is a repository-wide grep), 3, 4, 4b,
6, 7, 8, 10, 11, 12, 13, 14 all match the one-line description of the unit
they are assigned to, and 9a is correctly marked not this feature's. Two
rows are real but sit over a genuine defect elsewhere in the same plan (2 and
5, see R1 and R2). One row, 4a, is a defensible but not obviously singular
call: "arm binds a hash the human supplied" is assigned entirely to 035, the
operator surface, when the actual hash comparison against the currently
committed configuration reads more naturally as 032's job, since 032 is the
unit described as "bound to the frozen configuration hash" and would be the
one refusing to write an arm record on a mismatch, with 035 only collecting
and forwarding what the human typed. Not filed as a numbered finding: the
boundary between "collects the input" and "validates and stores it" is
genuinely arguable, unlike the sharp, checkable contradictions below, and
splitting every close call into a finding is the "manufactured to look
rigorous" failure mode this task named directly.

The table is real. It did the job N5, T2, and T3 asked for, closing all
three spec-level criteria's ownership gap, and doing so surfaced two new,
checkable problems rather than manufacturing decorative coverage.

### Part 2: what these fixes broke

| # | Severity | Location | Summary |
|---|---|---|---|
| R1 | HIGH | plan.md lines 159, 218-224, 233-236 | Criterion 5's correct assignment to UNIT-031 requires 031 to read UNIT-032's arm record at call time, but UNIT-031's own "Depends on" column omits 032, and the Sequencing section states outright that 031 depends otherwise only on merged units, which 032 is not. |
| R2 | MEDIUM | plan.md lines 183-186, 201 | UNIT-034's one-line description enumerates the criteria it owns by number and the enumeration omits criterion 2, while the criterion table assigns half of criterion 2 to 034. |

#### R1, HIGH: the criterion-5 fix creates a dependency the plan explicitly denies

UNIT-031's row: "UNIT-031 paper broker client | the network | `broker/client.py`,
`tests/execution/test_client.py` | execution | 030b, 010, 011, 012, 015, 017 |
execution-safety-reviewer" (plan.md, line 159). No 032.

The criterion table and the surrounding prose require the opposite. Criterion
3: "032 defines the value, 031 requires it" (line 200). 032's own
description: the arm record is "readable as the value the submit path
requires" (line 170), and the submit path is 031's, not 034's, exactly the
point Q1 establishes. Criterion 5's justification is explicit that 031 must
perform the read itself: "only the unit making the call can guarantee that"
(lines 219-220), and 034's own line now says the same thing from the other
side, "the arm is read at the call it authorises, which is 031's job" (line
184). Put together, 031's code has to reference a value type 032 defines and
call a function 032 exposes to read the current arm state, at the moment of
the network call.

The Sequencing section says this cannot be so: "032 and 033 have no
dependency on it, on each other, or on anything unmerged, so they can be
claimed and dispatched together immediately. 031 waits only for the
dependency unit, then joins them. Each depends otherwise only on merged
units" (plan.md, lines 233-236). "Each depends otherwise only on merged
units" is false under the design criterion 5 and criterion 3 both require:
031 depends on 032, and 032 is not merged, it is one of the three units this
same sentence says can be "claimed and dispatched together immediately."
This is not a hypothetical collision the way UNIT-020/UNIT-021's globs were;
it is the same document asserting, in one place, a design that requires a
cross-unit reference, and in another place, that no such reference exists.
An implementer handed UNIT-031's intake in isolation, the way `spec-tasks`
would hand it out, has no declared reason to expect UNIT-032 to exist yet,
and no line tells them to import from it.

The fix is small and named rather than merely asserted: add 032 to UNIT-031's
"Depends on" column, and correct the Sequencing section's "each depends
otherwise only on merged units" to say what is actually true, that 031
depends on 032 for the arm-read it must perform, that 032 and 033 can still
be claimed together since neither depends on the other, and that 031 now
waits on both 030b and 032 rather than 030b alone.

Checked directly rather than asserted: this is not only a glob question.
`scripts/coord.py`'s own claim gate, `check_claimable`, reads each declared
`depends_on` entry and refuses outright if any is not `merged`: "unmet =
[dep for dep in meta.get('depends_on', []) if str(get(units, dep)[0]['state'])
!= 'merged']" followed by "raise UnitError(f'{unit_id} depends on unmerged
units: ...')" (`scripts/coord.py`, lines 262-266), the same mechanism D-018's
own test suite exercises for exactly this refusal. Once 032 is added to
031's `depends_on`, `coord.py claim UNIT-031` would be refused for as long as
UNIT-032 is anything short of `merged`, which is the opposite of "claimed
and dispatched together immediately." The Unit boundaries section's claim
that "`coord.py` will accept 031, 032, and 033 as one batch" (line 165) is
therefore not only unchecked, it is wrong under the corrected dependency
list: 032 and 033 can still be claimed together, since neither depends on
the other, but 031 could not join them until 032 merges. `paths_overlap`
alone was the check pass three and four ran and it is not the check this
finding turns on; the dependency gate at lines 262-266 is.

#### R2, MEDIUM: 034's own enumerated criteria list and the criterion table disagree

034's one-line description gives what reads as a complete list: "Criteria
4b, 6, 7, 8, 9, and 14 live here" (plan.md, line 186), and the same sentence
explicitly excludes criterion 5 by name a few words earlier, "which is 031's
job and criterion 5." A reader relying on this line alone would conclude 034
has no stated role in criterion 2.

The criterion table disagrees: "2 credential never recorded | 031 raises
none carrying one, 034 records none" (plan.md, line 201). Half of criterion 2
is 034's by the table's own account, "the orchestrator records no entry
carrying one" is also spec.md's own wording for the same half (spec.md,
lines 139-140). The two sections of the same plan do not name the same set
of criteria for UNIT-034. Small, and not load-bearing the way R1 is, since
nothing here contradicts what 034 must actually build, only which section of
the plan says so; filed as MEDIUM, the same bar T6's terminology drift and
Q2's stale paragraph were filed at. Fix: add "2" to 034's enumerated list, or
drop the enumeration in favour of pointing at the table once, since
maintaining the same information in two places is what produced this and R1
both.

### Fitness to proceed to `spec-tasks`

Four of the five items sent for verification are genuinely resolved: T5, Q1,
Q2, and the N5/T2/T3 criterion table. Q3 is partially resolved, a sound new
argument added alongside an old one that is still imprecise, and the
imprecision does not change the plan's actual, mechanically-verified
conclusion (a separate dependency unit is correct). This is real progress,
on the same pattern as the fourth pass: most of what was claimed fixed
actually was.

**Not yet fit.** One new HIGH finding, R1, is a direct textual contradiction
inside `plan.md` itself: the design the criterion table and two units' own
one-line descriptions require (031 reads 032's arm value at call time) is
flatly incompatible with the Sequencing section's own sentence that 031
"depends otherwise only on merged units." This is not a manufactured
finding raised to justify a sixth pass; it is the same class of defect this
project's own reviewers have caught before (UNIT-020/UNIT-021's glob
collision, D-027's own concurrent-lockfile concern) and it would surface at
`coord.py claim` time or earlier, the moment UNIT-031's intake is written
against a "Depends on" list that does not include the unit its own submit
path must call into. R2 is real but does not block on its own, the same way
Q2 and Q3's residue did not block the fourth pass's own verdict.

Recommended next step, and it is the only thing blocking: add UNIT-032 to
UNIT-031's declared dependencies, and correct the Sequencing section's
"depends otherwise only on merged units" sentence and the "coord.py will
accept 031, 032, and 033 as one batch" line to say what the corrected
dependency graph actually allows, 032 and 033 together, 031 only once 032 is
merged, rather than all three at once. That is a same-document edit, not a
design change: the assignment of criterion 5 to 031 is correct and should
not move. R2 is one word away from closed, add "2" to UNIT-034's enumerated
list. Once both land, a sixth pass should not be
needed to re-run the six passes from the beginning; it would only need to
confirm these two specific edits, the way this pass confirmed five.
