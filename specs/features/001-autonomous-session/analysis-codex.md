# Final Codex analysis: Feature 001, autonomous paper trading session

This is a fresh adversarial pass over the completed feature specification, its
plan, all six unit intakes, the merged source they name, the governing rules,
and the installed source of the external libraries they rely on. Findings from
the five passes in `analysis.md` are not repeated or counted here.

The merged-source check used the current implementations, not the prose that
describes them. In particular, it checked `PaperTransport`,
`TransportResponse`, `RecordedSubmissionAttempt`, `DecisionLedger`,
`BrokerTruthSource`, `PositionSource`, `AccountSnapshot`, and `flatten`
directly. The external-source check used cached `httpx` 0.28.1 and
`alpaca-py` 0.44.0 source.

## Findings

| ID | Severity | Pass | Location | Summary |
|---|---|---|---|---|
| C1 | CRITICAL | Consistency / conflict with rules | UNIT-031 Contract and AC-7; `broker/endpoint.py` | The merged transport has neither an HTTP method nor a response body, so it cannot perform or parse the GET, POST, PATCH, and DELETE operations UNIT-031 promises without bypassing the single asserted path or changing a merged unit. |
| C2 | CRITICAL | Conflict with rules / coverage | UNIT-031 Contract and AC-5; UNIT-034 AC-6 | The proposed submission boundary requires an arm value but does not require or validate the risk approval, durable submission attempt, canonical payload binding, stable client order ID, or smoke-test cap that `AGENTS.md` says the only order path must enforce. |
| C3 | CRITICAL | Conflict with D-017 / consistency | UNIT-032 Scope and AC-5; `config/risk.toml`; `RiskConfig` | UNIT-032 says UNIT-005 committed the maximum arm lifetime. It did not. No such key or field exists, and UNIT-032 does not own the config paths needed to add one. |
| C4 | CRITICAL | Conflict with rules / underspecification | spec criterion 5; UNIT-031 AC-6; build plan section 7 | Reading the arm immediately before submit is not atomic with disarm. A controlled race can still submit after disarm returns, and no unit owns the one-process lock or equivalent serialization the build plan requires. |
| C5 | CRITICAL | Unfalsifiable criterion | UNIT-034 AC-7 | "No trading rule of its own" is not falsified by the stated arithmetic and threshold observation. Structure or exit selection can be added with no arithmetic at all, so the criterion can pass while its claimed invariant is false. |
| C6 | CRITICAL | Conflict with rules / coverage | UNIT-032 Contract; UNIT-034 Scope; UNIT-035 Scope | Arming and disarming change the session state, but no intake owns recording those operator-driven transitions in the append-only ledger. The stated ledger writer only runs scheduled invocations. |
| C7 | CRITICAL | Conflict with D-010 / consistency | UNIT-006 AC-4 and test list; UNIT-031 paths | UNIT-006 deliberately merges a repository test forbidding every `httpx` import. UNIT-031 must add such an import, but its globs exclude the test that the intake says will later "move". The full quality gate therefore cannot pass within UNIT-031's boundary. |
| H1 | HIGH | Coverage / consistency | spec Scope and criterion 9; UNIT-017; UNIT-031; UNIT-034; UNIT-035 | No unit owns creating and submitting cancel, replace, or closing-order requests. The merged `flatten` only observes already-materialized closing intents and positions, while the new intakes repeatedly assign exit and flatten to it as though it placed orders. |
| H2 | HIGH | Underspecification / coverage | UNIT-034 Contract, AC-5, AC-9, and test list | The orchestrator names no collaborator interfaces, invocation result, session-ledger schema, or durable projection from a session to its known order IDs. Its "same evidence trail" criterion is also undefined. Tests can satisfy the intake with doubles while never proving restart reconstruction from the real ledger. |
| H3 | HIGH | Conflict with rules / coverage | spec Scope; UNIT-031 Scope; UNIT-034 Source of truth and tests | Account and clock reads are in feature scope but absent from UNIT-031's protocols, parsing contracts, criteria, and tests. No current type represents broker clock truth, and no intake proves the closed-market, stale-clock, account-uncertainty, or stale-approval refusal required by the execution rules. |
| H4 | HIGH | Unfalsifiable test / conflict with secret boundary | UNIT-031 AC-4 and test list; installed `httpx` source | `httpx` exceptions retain the originating `Request`, whose headers contain the credentials. Searching exception text, arguments, and formatted tracebacks can pass while the exception still carries the sentinel in `exc.request.headers`. |
| H5 | HIGH | Consistency / underspecification | spec criterion 3; UNIT-032 Contract and AC-3; `execution/lifecycle.py` | The named precedent is false. `RecordedSubmissionAttempt` is a public dataclass with a public constructor, so it does not demonstrate a value only a durable read can produce. Copying its shape would violate UNIT-032's own AC-3. |
| M1 | MEDIUM | Consistency | plan unit table and criterion table; `specs/000-INTAKE.md`; unit frontmatter | The plan still calls the dependency unit `UNIT-030b`, while the intake is UNIT-006. The decomposition table in `000-INTAKE.md` lists neither UNIT-006 nor UNIT-031 through UNIT-035, and UNIT-006's copied delegation note incorrectly calls its shared paths execution-lane paths. |

## Detail

### C1: the merged transport cannot express the broker client contract

The feature Scope requires one `PaperTransport` path for placing, cancelling,
and replacing orders and for account, position, activity, and clock reads.
UNIT-031 also requires response parsing through `parse_order`,
`parse_activity`, and `parse_position`.

The actual merged interface is narrower:

```python
class PaperTransport(Protocol):
    def request(
        self,
        url: str,
        body: bytes,
        *,
        follow_redirects: Literal[False],
    ) -> TransportResponse: ...

@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    location: str | None
```

There is no HTTP method, query parameter surface, response body, or decoded
payload. `send_paper_request` preserves the same omissions. Installed
`alpaca-py` source confirms that the required operations use distinct verbs:
submit is POST, lookup and account reads are GET, replace is PATCH, and cancel
is DELETE. Parsing is impossible from status and Location alone.

An implementation can only proceed by changing the merged endpoint contract,
or by adding side-channel `httpx` methods that do not flow through the merged
Protocol. The first violates the feature's Out list and UNIT-031's globs. The
second violates the one-path endpoint assertion the Scope and `AGENTS.md`
require. A prerequisite unit must widen the transport and response contract,
or the spec must explicitly replace it. This cannot be improvised inside
UNIT-031.

### C2: the only order path does not enforce the full submission authority

`AGENTS.md` requires the application order adapter to enforce the paper
endpoint, arm state, risk approval, idempotent client order IDs, broker
reconciliation, and the one-contract smoke-test cap. The execution rule also
requires the approval to bind the canonical payload and frozen hashes.

UNIT-031 makes only the arm value structural. It names no submit signature and
requires no `RiskApproval`, `RecordedSubmissionAttempt`, `SubmissionDecision`,
canonical payload hash, approval expiry check, or sizing mode. UNIT-034 says it
uses UNIT-012's primitives, but that does not stop another caller from reaching
the UNIT-031 submit surface with an arm and arbitrary bytes.

The correction is a narrow public submit capability whose signature and
runtime checks bind all of those facts to the exact bytes sent. Tests must
attempt each missing, expired, mismatched, and mutated input through every
public order path. The low-level raw transport must not itself become an
unguarded application order path.

### C3: the committed arm lifetime does not exist

UNIT-032 says expiry uses "the maximum lifetime UNIT-005 committed" and AC-5
requires reading it from committed configuration. UNIT-005 committed exactly
three other values: snapshot age, daily loss fraction, and peak-to-valley
fraction. Current `config/risk.toml` and `RiskConfig` contain no arm lifetime.

UNIT-032 owns only `execution/arm.py` and its test. It therefore has three bad
choices: invent a literal against D-017, add config files outside its globs, or
leave expiry caller supplied and fail its own AC-5. The value and its unit
ownership must be clarified before a claim. This makes UNIT-032 the boundary
most certain to move, unless a seventh prerequisite unit is added for the
frozen arm-duration setting.

### C4: criterion 5 has a time-of-check to time-of-use race

The earlier passes accepted "read immediately before call" as the criterion 5
mechanism. It does not establish the criterion's own falsifier.

A deterministic counterexample is:

1. Submit invocation reads a live arm.
2. It pauses before the HTTP send.
3. A separate disarm invocation removes the arm and returns success.
4. The paused invocation sends the order.

The order is submitted after disarm returned even though the read was
immediately before the transport call in source order. UNIT-031's proposed
test disarms between two completed submissions and cannot exercise this
window. The build plan separately requires one-process ownership or a reliable
lock, but scheduling is out of UNIT-034 and no intake owns such a lock.

The spec needs a cross-process concurrency rule. For example, disarm and the
submit critical section can share a lease, with disarm not returning until an
in-flight send is resolved or conservatively reconciled. A controlled-barrier
test must pause after the arm read and before the send. Emergency halt and
flatten still need a path that cannot be starved by that serialization.

### C5: UNIT-034 AC-7 is not falsifiable as written

AC-7 claims the module contains no sizing, pricing, structure-selection, or
exit rule, then says arithmetic on money or an undelegated threshold
comparison falsifies it. That observation is available, but it is not capable
of falsifying the whole claim. `candidate = candidates[0]`, a hard-coded
structure-kind branch, or selection of the first exit action adds trading
policy without arithmetic or a threshold.

This cannot be cleared by opinion during review. The intake needs an exact
collaborator and call contract, an allowed decision vocabulary, and tests that
show collaborator outputs are passed through unchanged. A constrained import
and call graph can supplement that behavioral test. Until then AC-7 can pass
while the prohibited behavior exists, which is CRITICAL under the skill's
unobservable-criterion rule.

### C6: operator arm and disarm transitions have no ledger owner

UNIT-032 explicitly says the ledger still records arming and disarming.
UNIT-033 defines `Disarmed` to `Ready` and the disarm edges. The plan assigns
transition writes to UNIT-034. UNIT-035, however, calls UNIT-032 directly for
arm and disarm and says only halt and flatten invoke UNIT-034.

If an operator arms or disarms and no scheduled scan follows, the durable arm
store changes while the append-only ledger has no corresponding state
transition. That contradicts spec criterion 6 and the global rule preserving
an append-only audit path for decisions and state transitions. The responsible
unit must also define crash ordering between the arm store change and the
ledger write, otherwise either ordering can leave the two durable truths in
disagreement after a kill.

### C7: UNIT-006 merges a test UNIT-031 must break but cannot edit

UNIT-006 AC-4 and its test require that no source file import `httpx`. The
intake states that this assertion will "move" when UNIT-031 lands. A merged
test does not move by prose. UNIT-031's declared paths are only
`broker/client.py` and `tests/execution/test_client.py`, so it cannot remove or
amend `tests/test_dependencies.py`. Once UNIT-031 imports `httpx`, the full
repository test run fails exactly as UNIT-006 intended.

The transient assertion must not merge, or UNIT-031 must explicitly own the
later test amendment in a decomposition that respects D-010. An acceptance
criterion designed to expire in the next unit is not a durable regression
test.

### H1: no unit owns cancellation, replacement, or an actual closing order

The feature says the transport carries place, cancel, and replace, criterion 9
requires cancel or fill plus exit, and the operator must be able to flatten.
UNIT-031 specifies and tests submit only. UNIT-034 assigns exit and flatten to
UNIT-017. The actual merged `flatten` performs no I/O, creates no closing
payload, and submits nothing. Its own intake explicitly records that cancelling
working entries is unowned.

UNIT-035 then says halt and flatten invoke UNIT-034, while UNIT-034 exposes no
halt or flatten mode in its Contract or acceptance criteria. A fake broker can
make the tests look complete only if the new unit invents the missing order
actions inside a module whose AC-7 forbids trading logic.

This is a requirement with no implementing scope, so it is HIGH. Add explicit
units or contracts for cancel, replace, and authorized closing-intent creation
and submission, including partial-fill and flatten-failure paths.

### H2: the restart and evidence contracts are not defined

UNIT-034's public contract is "one entry point that takes the collaborators it
needs" and returns "a record." It does not name either. It also defines no
ledger kind or payload for session transitions and no durable index from a
session ID to the client order IDs needed to build UNIT-015 `KnownOrder`
values. The merged `DecisionLedger` reads by a caller-supplied subject ID and
does not enumerate submission subjects for the orchestrator.

This matters to the stated order of operations: reconciliation needs the known
orders materialized from durable state, but the intake places reconciliation
before rebuilding session state from the ledger. A test double can hand the
orchestrator a ready-made list and conceal that missing projection.

AC-9 adds a second ambiguity. A no-trade run cannot literally have the same
submission, fill, and exit entries as a trading run, while "records less" does
not define which common fields and stages must be present. Define the
collaborator protocols, result record, session identity, ledger schema,
projection algorithm, conditional evidence sections, and fault-injection
points before implementation.

### H3: account and clock safety gates are unowned

The spec puts account and clock reads through the broker path. UNIT-031 claims
only `BrokerOrderLookup`, `BrokerTruthSource`, and `PositionSource`. These
provide order, activity, and position facts. There is no account-read or
clock-read protocol, no account or clock parser, and no broker clock type in
merged source.

UNIT-034 cites execution-rule bullet 6, but its criteria and tests cover
unknown orders and unexplained positions only. They do not test a closed or
closing market, stale clock, uncertain account, stale approval, feed change,
or kill switch. Existing `AccountSnapshot` is a risk input, not a broker
adapter, and nothing in the intakes constructs it from broker truth.

Two competent implementations will either invent these facts inside the
orchestrator, contrary to AC-7, or omit them and violate the fail-closed rules.
The broker boundary needs typed account and clock observations, and the
orchestrator needs explicit criteria for every rule-bullet-6 refusal it is
responsible for sequencing.

### H4: the credential test misses credentials retained by `httpx` errors

Installed `httpx` 0.28.1 source sets the originating `Request` on
`RequestError`, and `HTTPStatusError` retains both its `Request` and
`Response`. An authenticated request stores credentials in `Request.headers`.
The request `repr` omits them, so the proposed checks of messages, arguments,
and formatted tracebacks can all pass while `exc.request.headers` still holds
the sentinel.

UNIT-031 must translate every library exception into a sanitized project
error without retaining a secret-bearing request, response, cause, or context.
The test must inspect the recursive exception object graph and any recordable
locals or structured fields, not only strings. Redirect behavior itself is
viable: the same installed source confirms that `follow_redirects=False`
returns the first redirect response instead of sending the generated next
request.

### H5: `RecordedSubmissionAttempt` is not the precedent the spec says it is

Spec criterion 3 and UNIT-032 say to follow UNIT-012's
`RecordedSubmissionAttempt` shape because only a durable read can construct
one. The actual merged type is exported and declared as a normal frozen
dataclass with a public two-argument constructor. Tests elsewhere construct it
directly.

The new arm capability can still be made narrower, but the intake must define
that construction rather than refer to a property the precedent does not
have. `EndpointConfiguration`, whose public initializer raises and whose
resolver-bound factory creates the instance, is closer to the intended local
pattern. The decisive test must attempt the actual public import and
constructor surfaces the implementation ships.

### M1: unit identity and registry terminology drift after `spec-tasks`

The plan still uses provisional `UNIT-030b` in its unit and criterion tables,
while the real intake and dependencies use UNIT-006. The decomposition table
in `specs/000-INTAKE.md` stops at UNIT-030 and therefore omits all six feature
units even though it says the table records the decomposition. UNIT-006's
copied delegation paragraph also says its paths are execution lane paths,
while its own frontmatter correctly says `lane: shared`.

`coord.py` discovers the intake files, so this does not by itself block a
claim. It does make the plan, registry prose, and implementable artifacts name
different decompositions. Replace provisional IDs and add the six final rows.

## Criterion observability and coverage summary

| Spec criterion | Final observation check |
|---|---|
| 1 | Observable by repository scan and endpoint tests. |
| 2 | Observable only if exception object graphs are searched, which the UNIT-031 test omits. See H4. |
| 3 | Observable, but its named type precedent is false and the submit boundary is incomplete. See C2 and H5. |
| 4 | Observable at the expiry boundary, but no committed duration exists. See C3. |
| 4a | Observable by display, mutation, and confirm tests. |
| 4b | Observable by config mutation before an invocation. |
| 5 | Observable with a controlled concurrent race. The proposed sequential test cannot falsify it. See C4. |
| 6 | Observable from ledger projection, but arm and disarm have no writer. See C6. |
| 7 | Observable with a broker lookup and duplicate-order count. |
| 8 | Observable with an unknown broker state and attempted entry. |
| 9 | Observable only after real cancel or close actions exist. See C1 and H1. |
| 9a | Correctly outside this feature and still blocked by G0. |
| 10 | Observable by the offline default suite. |
| 11 | Observable by source scan. |
| 12 | Observable with an `httpx` mock transport; installed source confirms the mechanism is available. |
| 13 | Observable as a fresh process, but no callable halt or flatten contract exists between UNIT-035 and UNIT-034. See H1. |
| 14 | Observable only after the durable session projection is specified. See H2. |

Every outcome traces to a criterion, but several criteria do not trace to an
implementable unit boundary. The uncovered capabilities are the full broker
HTTP shape, account and clock truth, the complete order authorization gate,
cancel and close submission, arm duration configuration, concurrent invocation
serialization, and operator-transition ledger writes.

## Six passes

- Ambiguity: H2 and H3. The orchestrator's collaborator, result, ledger, and
  no-trade evidence shapes are not defined, and account or clock behavior is
  left for an implementer to invent.
- Unfalsifiable criteria: C5. UNIT-034 AC-7's stated observation cannot falsify
  its claimed absence of trading rules. H4 is a test-observation gap of the same
  family for secret-bearing exception attributes.
- Underspecification: C1, C4, H1, H2, H3, and H5. Each permits materially
  different implementations, or no implementation within the declared paths.
- Conflict with project rules: C1, C2, C3, C4, C6, and C7. They conflict with
  the single asserted order path, deterministic risk approval, D-017, the arm
  boundary, append-only transition evidence, or D-010.
- Coverage: C2, C3, C6, H1, and H3. Required safety facts or actions have no
  owning acceptance boundary.
- Consistency: C1, C3, C7, H1, H5, and M1. Claims about merged interfaces,
  prior units, and final unit identities do not match the current artifacts.

## Decomposition verdict

The globs are disjoint, but disjointness is not enough. UNIT-031 cannot satisfy
the merged transport protocol it is told not to change. UNIT-032 cannot read a
configuration value that does not exist. UNIT-034 is asked to reconstruct and
exit through contracts that are not present. UNIT-035 calls a halt and flatten
surface UNIT-034 never defines. UNIT-006 leaves a test that blocks its own
first consumer.

UNIT-032 is the boundary most certain to move. Its committed-lifetime
criterion requires `config/risk.toml`, `alphaledger.config`, and config tests,
none of which it owns. A separate prerequisite config unit is the cleaner
alternative if widening UNIT-032 would violate lane ownership.

The read-only `coord.py check` result is mechanical, not a fitness verdict:
UNIT-006, UNIT-032, and UNIT-033 currently pass the dependency gate;
UNIT-031, UNIT-034, and UNIT-035 are refused until their declared prerequisites
merge. The findings above mean even the mechanically claimable first batch is
not ready.

## Verdict

Seven CRITICAL findings, five HIGH findings, and one MEDIUM finding.

**The six intakes are not fit to claim or implement from.** The next process
step is `spec-clarify` for the CRITICAL and HIGH findings, followed by plan and
intake amendments and one more targeted analysis. It was not run here because
this task explicitly permits only the new analysis file and forbids edits to
the spec, plan, and intakes.
