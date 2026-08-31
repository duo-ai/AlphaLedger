# Plan: the autonomous paper trading session

Derived from `spec.md` in this directory, after two `spec-analyze` passes and
one `spec-clarify` session. Read the spec's Clarifications first; three
decisions there shape everything below.

## Approach

The merged code already declares the seams this feature has to fill. UNIT-012
declares `BrokerOrderLookup`, UNIT-015 declares `BrokerTruthSource`, UNIT-017
declares `PositionSource`, and UNIT-010 declares `PaperTransport`. Every one is
a Protocol with no live implementation. So the work is not to design an
integration layer; it is to satisfy four Protocols that already exist, and then
to sequence the units behind them. That is why nothing here amends a merged
unit, and why the spec's Out list can forbid it without making the feature
impossible.

The decomposition follows what a component needs in order to do its job, which
is a question an implementer can answer per function without asking anyone.
Nothing but its inputs means the session state machine. Durable state but no
network means the arm record. The network but no decisions means the broker
client. Sequencing the others and deciding means the orchestrator. A person
means the operator commands. The lockfile, which is nobody's job and everybody's
blocker, means a dependency unit of its own. Six answers, six units, no shared
files, which is what lets most of them run at once rather than in a queue.

The orchestrator is deliberately thin. Every decision it appears to make is
already owned: sizing by UNIT-013, structure choice by UNIT-014, rung prices by
UNIT-019, reconciliation by UNIT-015, exits and flatten by UNIT-017, the order
lifecycle by UNIT-012. Its job is to call them in order, record every
transition, and stop when any of them says stop. If it grows logic of its own,
that is the signal the decomposition is wrong, not that the orchestrator needs
to be clever.

Rejected: one unit for the whole session, on the argument that transport, arm,
and machine are meaningless apart. It is true that none of them is useful alone
and false that they should be one unit. They fail differently, they are
reviewed against different rules, and a single unit would be the largest in the
project by a wide margin on its most safety critical path. This project's own
evidence is that large units burn review rounds: UNIT-025, the largest so far,
took two, and the units that cleared first time were small ones with a single
seam. Four units also let three run in parallel, which one cannot.

## Existing surface it builds on

Named exactly, because a plan that silently reimplements something merged is
the most expensive kind of wrong.

- `alphaledger.broker.endpoint`: `PaperTransport`, `TransportResponse`,
  `EndpointConfiguration`, `assert_paper_endpoint`, `resolve_paper_base_url`,
  `validate_process_start`, `LiveEndpointError`, `IndeterminateResponseError`.
- `alphaledger.execution.orders`: `build_mleg_order`, `order_payload_hash`,
  `canonical_bytes`, `parse_order`, `parse_activity`, `parse_position`,
  `BrokerOrder`, `BrokerActivity`, `BrokerPosition`, `BrokerOrderStatus`.
- `alphaledger.execution.lifecycle`: `client_order_id`, `OrderState`,
  `OrderEvent`, `transition`, `is_broker_terminal`, `is_lifecycle_terminal`,
  `blocks_new_entries`, `BrokerOrderLookup`, `RecordedSubmissionAttempt`,
  `decide_submission`, `recover_submission`, `SubmissionDecision`,
  `RecoveryDecision`, and the five reason constants.
- `alphaledger.execution.reconcile`: `reconcile`, `BrokerTruthSource`,
  `KnownOrder`, `ReconciliationReport`.
- `alphaledger.execution.killswitch`: `evaluate_kill_switch`, `flatten`,
  `EquityState`, `PositionSource`, `FlattenReport`, `KillSwitchDecision`.
- `alphaledger.execution.ladder`: `step_ladder`, `LadderBudget`.
- `alphaledger.risk.approval`: `approve`, `AccountSnapshot`,
  `account_snapshot_hash`, `max_approved_quantity`, `is_expired`, `SizingMode`.
- `alphaledger.structure.chains`: `enumerate_candidates`, `ChainLookup`.
- `alphaledger.structure.pricing`: `rung_prices`.
- `alphaledger.ledger.decisions`: `DecisionLedger`, `LedgerEntry`,
  `SUBMISSION_ATTEMPT_KIND`, `ORDER_STATE_KIND`.
- `alphaledger.config`: `load`, `config_hash`, `FrozenConfig`, `RiskConfig`.

Four of those are Protocols with no implementation today, and satisfying them
is the whole of the broker client unit: `PaperTransport`, `BrokerOrderLookup`,
`BrokerTruthSource`, `PositionSource`.

## Package before bespoke

- HTTP for the order and account path. `httpx` is the candidate and is already
  in the resolved set per D-012. It fits: it exposes explicit redirect control,
  which is what `PaperTransport`'s `follow_redirects: Literal[False]` needs to
  mean something at run time rather than only at type check time. `urllib` from
  the standard library would also work and is rejected: it makes connection
  reuse, timeouts, and redirect control the caller's problem, and this is the
  one path in the project where those are safety relevant.
- The Alpaca SDK for the same path. `alpaca-py` is rejected here and the reason
  is recorded in the spec's Clarifications rather than restated: its
  `TradingClient` carries a `paper: bool` that resolves to the live host.
- Retry policy. `tenacity` is the obvious candidate. Rejected for the order
  path: a retry that cannot tell a timed out submit from a rejected one is
  exactly how a duplicate order happens, and UNIT-012 already owns that
  decision through `decide_submission` and `recover_submission`. A general
  retry decorator would sit above that logic and undo it. Reads may retry, and
  a hand written bounded retry with no shared state is small enough not to earn
  a dependency.
- The session state machine. `transitions` and `python-statemachine` both
  exist. Rejected for the same reason UNIT-012 recorded when it hand rolled the
  per-order table: the machine is seven states and a fixed edge set, the value
  is in refusing an illegal edge loudly, and a library adds a dependency plus a
  second vocabulary for something a frozen mapping expresses completely.
- A CLI framework. `click` and `typer` both fit and either is reasonable. The
  arm surface is three commands with one argument between them, so the standard
  library `argparse` is enough and adds nothing to the lockfile. Revisit if the
  surface grows past a handful of commands.
- Market data clients. Out of scope here entirely, see Risks.

## File layout

Created:

```
src/alphaledger/broker/client.py          the four Protocol implementations
src/alphaledger/execution/arm.py          the durable arm record
src/alphaledger/execution/session.py      the session state machine
src/alphaledger/execution/orchestrator.py one invocation, start to finish
src/alphaledger/cli.py                    arm, disarm, halt, flatten, scan
tests/execution/test_client.py
tests/execution/test_arm.py
tests/execution/test_session.py
tests/execution/test_orchestrator.py
tests/test_cli.py
```

Changed: `pyproject.toml` and `uv.lock`, to add `httpx`, and nothing else.
Every merged source file stays as it is, which is the spec's Out list expressed
as a file list.

That dependency is its own unit and merges before any other here, and the
reason is D-027 rather than tidiness. D-027 widened UNIT-025's globs onto the
lockfile and recorded plainly that this was safe only because UNIT-025 was the
sole claimed unit at the time, that it bends D-010, and that it is not a
precedent. It rejected a separate unit as ceremony for a two line change with
no other writer to protect against. Stated precisely, because two earlier
drafts of this paragraph argued from D-027's revisit condition and both misread
it. That condition is scoped to "while UNIT-025 is open", and UNIT-025 merged
on 2026-08-30, so it cannot apply here either way and no reading of it decides
anything. The reason to
separate the change is the one D-027 states about itself rather than a
condition it sets for others: it bends D-010, it says so, and it says it is not
a precedent. Repeating a bend that its author labelled unrepeatable needs a
better argument than convenience, and here there is none, because the change is
two lines that block five units and can simply land first. Verified rather than
assumed: `httpx` appears zero times in `pyproject.toml` and `uv.lock`.

Broker tests live in `tests/execution/` because UNIT-010's do, in
`tests/execution/test_endpoint.py`. Consistency with where the existing broker
tests already are beats matching the source tree.

## Unit boundaries

The discriminator is the one stated in Approach above. Repeated here in short
form only: what does this need in order to do its job? Its inputs alone, durable
state, the network, the other units, an operator, or the lockfile.

| Unit | Needs | Owns | Lane | Depends on | Reviewer |
|---|---|---|---|---|---|
| UNIT-030b http dependency | the lockfile | `pyproject.toml`, `uv.lock` | shared | none | code-reviewer |
| UNIT-031 paper broker client | the network | `broker/client.py`, `tests/execution/test_client.py` | execution | 030b, 032, 010, 011, 012, 015, 017 | execution-safety-reviewer |
| UNIT-032 arm record | durable state | `execution/arm.py`, `tests/execution/test_arm.py` | execution | 004, 005, 016 | execution-safety-reviewer |
| UNIT-033 session state machine | nothing but arguments | `execution/session.py`, `tests/execution/test_session.py` | execution | 001, 012 | execution-safety-reviewer |
| UNIT-034 session orchestrator | the other three | `execution/orchestrator.py`, `tests/execution/test_orchestrator.py` | execution | 031, 032, 033, 004, 005, 011, 012, 013, 014, 015, 016, 017, 018, 019 | execution-safety-reviewer |
| UNIT-035 operator commands | an operator | `cli.py`, `tests/test_cli.py` | execution | 032, 034 | execution-safety-reviewer |

Every glob is disjoint, so `coord.py` will accept 031, 032, and 033 as one
batch.

What each is, in one line, since the intakes will say the rest:

- **031** implements `PaperTransport` over `httpx` with redirects refused at run
  time, and satisfies `BrokerOrderLookup`, `BrokerTruthSource`, and
  `PositionSource` by parsing responses through UNIT-011's existing parsers. It
  makes no decisions and holds no state.
- **032** owns the arm record: written by a human action, bound to the frozen
  configuration hash, time limited by a committed threshold, durable across
  processes, and readable as the value the submit path requires. Criterion 3
  lives here.
- **033** owns the seven session states and their edges, including the two the
  design diagram omits and the rules require. Pure, so an illegal edge raises
  and nothing else happens.
- **034** is one invocation: verify the configuration hash against the arm,
  reconcile, rebuild session state from the ledger, decide, act, record, exit.
  It does not load the arm once and carry it; the arm is read at the call it
  authorises, which is 031's job and criterion 5. An earlier draft of this line
  began "load the arm", which is the cached read that criterion forbids.
  Criteria 4b, 6, 7, 8, 9, and 14 live here, and the recording half of
  criterion 2. The criterion table is the complete assignment; this line is a
  summary and defers to it.
- **035** is the operator surface, and operator means the human who arms: the
  two step arm, disarm, and the halt and flatten invocations criterion 13
  requires to exist independently of the scan.

## Which unit satisfies which criterion

Added after a fourth analysis pass observed the same failure three times: a
criterion changed in the spec and no unit picked it up in the plan. Prose next
to a criterion is not an assignment. This table is, and it is the thing to
update when a criterion moves.

| Criterion | Owned by |
|---|---|
| 1 no live host, path, or switch | 030b, 031, and enforced repository wide |
| 2 credential never recorded | 031 raises none carrying one, 034 records none |
| 3 transport uncallable without an arm | 032 defines the value, 031 requires it |
| 4 expired arm blocks | 032 |
| 4a arm binds a hash the human supplied | 035 |
| 4b every invocation reverifies the hash | 034 |
| 5 disarm effective before the next submission | 031, which reads the arm at the call it authorises, not 034 at invocation start |
| 6 every transition recorded | 033 defines them, 034 writes them |
| 7 no second intent after a killed submit | 034, over UNIT-012's merged primitives |
| 8 refuses entries while a state is unknown | 034 |
| 9 one order end to end against a fake broker | 034, and the fake lives in its tests |
| 9a the same against the paper account | nobody here, this is the G1 gate |
| 10 no network in tests | every unit |
| 11 no `alpaca.trading` import, no live host string | 030b owns the dependency, criterion 1 covers the string |
| 12 no redirect followed at run time | 031 |
| 13 halt and flatten as their own invocations | 035 |
| 14 reconstruction agrees with the broker or refuses | 034 |

Criterion 5 is assigned to 031 deliberately and against the obvious reading.
The arm is 032's record and 034 is the sequencer, so 034 looks like the owner.
But the criterion is about when the read happens relative to the call it
authorises, and only the unit making the call can guarantee that. 034's own
description lists loading the arm as its first step, which is exactly the cached
read this criterion forbids, so leaving it with 034 would have written the
anti-pattern into the plan.

## Sequencing

The dependency unit merges first and alone. It is two lines and one lockfile,
and its whole purpose is that no other unit is open on those files while it
lands. Its number is provisional; `spec-tasks` assigns the real one against the
registry.

030b, 032, and 033 depend on nothing unmerged and on nothing here, so all three
can be claimed and dispatched together immediately.

031 waits for both 030b and 032. The dependency on 030b is the lockfile. The
dependency on 032 is a consequence of criterion 5 that an earlier draft of this
plan missed: assigning that criterion to 031 means 031 reads the arm value at
the call it authorises, so it needs the type 032 defines. `coord.py` refuses a
claim naming an unmerged dependency, so this is mechanical rather than
advisory, and the earlier claim that 031 could join the first batch was wrong.

That is the cost of putting criterion 5 in the right place, and it is worth
paying: the alternative was leaving it with 034, whose own description in this
plan contained the cached read the criterion forbids.

034 depends on 031, 032, and 033 because it is defined as the thing that
sequences them, and on every merged unit it calls. Those are enumerated in the
table rather than described, because an earlier draft wrote "and every unit it
sequences", which `spec-tasks` cannot turn into a `depends_on` list without
guessing. All of them are merged, so none of them delays the claim.

035 depends on 032 for the arm it writes and on 034 for the halt and flatten
paths it invokes. It is last because it is the human surface over everything
else, and because a CLI written before the thing it drives tends to fix the
wrong shape.

Nothing here depends on G0, and nothing here can be believed without it.
Criterion 9 is satisfiable against a recorded fake broker; criterion 9a is the
G1 gate and waits.

## Risks

**The spec claims market data scope that UNIT-028 already owns.** The spec's
Scope In lists `alpaca-py` market data clients for bars and news. UNIT-028,
titled "Fetch Alpaca bars and news into point-in-time records", declares
`src/alphaledger/data/alpaca.py` and is available in the research lane. Two
rows would own one capability. This plan allocates no market data work and no
file under
`src/alphaledger/data/`. The spec has since been narrowed to match, so the
conflict is closed; it is left recorded here because the plan flagging a defect
in its own spec, rather than quietly dropping the requirement, is the behaviour
worth keeping.

**The fake broker is the thing most likely to be wrong.** Criterion 9 is
satisfied against a recorded fake that replays real Alpaca response shapes, and
the shapes come from a published reference that D-024 says has never been
observed live, after a credentialed call returned 401. A fake built from a
reference can be confidently wrong in the same way the reference is. The
mitigation is that D-024 already names four defaults that would corrupt data
silently, so the fake should encode those as the hostile cases rather than the
happy path.

**The dependency unit is a serialisation point and a small one.** Every other
unit here is blocked behind two lines in `pyproject.toml`, which is an
unsatisfying shape. It is accepted because the alternative is widening a unit's
globs onto the lockfile while another lane holds a claim, which is exactly what
D-027 says not to do a second time. If it becomes a real delay, the answer is
to land it first and separately, not to fold it into UNIT-031.

**The arm's durable store may want to be the ledger.** UNIT-016 already owns
append only durable storage with restart semantics, and an arm record is a
durable fact about a session. Making 032 a separate store risks two durability
implementations with different failure modes; making it a ledger entry risks
bending a unit whose purpose is decisions rather than state. The intake for 032
has to settle this, and it is the decision most likely to move a file boundary
after this plan is written.
