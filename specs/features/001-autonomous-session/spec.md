# Feature 001: The autonomous paper trading session

## Problem

Twenty-three units are merged and nothing in this repository can place an
order. `src/alphaledger/broker/endpoint.py` declares `PaperTransport` as a
Protocol and no implementation of it exists; a grep for an HTTP client across
`src/` returns nothing. `config/risk.toml` commits `require_human_paper_arm`
and no code reads it, so the arm the rule requires is a stated intention rather
than a state anything holds. Nothing sequences a session.

The consequence is not that a feature is missing. It is that the project's
central claim is untested. Every component has been proven against in-memory
doubles, and the assertion that they compose into an agent that trades safely
for a day has never been exercised, because there is no path from a decision to
a broker and back.

G1 requires submitting, cancelling, closing and reconciling one MLeg paper
order through a tested adapter. G4 requires a full session with no manual order
decisions. Neither is reachable from the current tree, and no row in
`specs/000-INTAKE.md` owns the gap.

## Outcome

When this is done:

- A human can arm a frozen configuration once, and the system can then submit,
  manage, and exit paper orders for that session without further confirmation.
  Disarm, halt, and manual flatten remain available at any time.
- A single defined-risk MLeg order can be submitted to the paper endpoint,
  observed, cancelled or filled, reconciled against broker truth, and exited,
  with every transition recorded in the append-only ledger.
- Each scheduled invocation reconstructs the session from the ledger and broker
  truth before it acts, so a process killed at any point leaves the next
  invocation agreeing with the broker about what exists, and refusing new
  entries until it does. Reconstruction is the ordinary path, not a recovery
  path.
- A session that decides not to trade produces the same evidence trail as one
  that does.

## Scope

In:

- A concrete transport satisfying the merged `PaperTransport` Protocol,
  carrying credentials from the environment and never into a log, a ledger
  entry, or an error message. It carries everything that places, cancels, or
  replaces an order.
- Account, position, activity, and clock reads through the same merged
  `PaperTransport` Protocol, so every call that touches the trading host takes
  one path and one endpoint assertion.
- Nothing under `src/alphaledger/data/`. Market data is UNIT-028's, and this
  feature neither fetches bars nor news. The Clarifications entry that admits
  `alpaca-py`'s market data clients establishes only that they are safe to use,
  which is a fact UNIT-028 inherits; it does not claim the work. An earlier
  draft of this Scope listed those clients here, which would have put one
  capability under two rows.
- The session and arm state machine over the seven states design section 11
  names: disarmed, ready, working, open, exiting, closed, halted.

  It implements that diagram's transitions and two the diagram omits, because
  the diagram is incomplete and the rules outrank it. `Exiting` has exactly one
  outgoing edge there, to `Closed` on success, so a flatten that is failing has
  nowhere to go; `.claude/rules/01-safety.md` bullet 4 requires a fail closed
  halt on uncertainty with no exception for exiting, and
  `.claude/rules/30-execution.md` bullet 8 requires flatten failure to escalate
  while keeping entry disabled. UNIT-017 is merged and already reports exactly
  that condition, so the code can produce a fact the diagram gives the session
  nowhere to put. `Exiting -> Halted` is therefore required.

  Separately, `Disarmed` appears in that diagram only as the initial state, so
  a literal reading makes disarm unreachable once running, which contradicts
  section 11's own sentence that disarm remains available. A disarm edge from
  every non terminal state is therefore required.

  Both additions are deviations from a cited source and are recorded here
  rather than taken silently, per `AGENTS.md`'s instruction to surface a
  conflict rather than resolve it toward the more permissive reading.
- A two-step human arm action. The first step displays the frozen configuration
  hash and the limits it implies; the second arms only when the human passes
  that exact hash back. The result is a durable, time limited arm record bound
  to that hash, and a disarm that revokes it immediately.
- An orchestrator that sequences one session: scan, decide, approve, submit,
  reconcile, exit, and halt, calling the merged units rather than reimplementing
  any of them.
- Session reconstruction from broker truth and the ledger at the start of every
  invocation, never from memory carried across one.
- A durable arm record, because the arm outlives every process that reads it.

Out:

- Any change to the merged units this composes. If the orchestrator needs
  behaviour a unit does not expose, that is a change to that unit, specified
  separately and reviewed on its own terms.
- The per-order state machine, which is merged as UNIT-012 and is a different
  scope from the session machine. Section 11 carries the session diagram; the
  eleven per-order states come from `.claude/rules/30-execution.md` bullet 4.
- Live trading in any form. There is no live host, no live credential path, and
  no mode switch, per D-001.
- Model fitting, feature construction, and the research lane generally. The
  orchestrator consumes a frozen forecast; it does not produce one.
- The dashboard and any presentation surface. Presentation reads projections
  and never changes trading state.
- Passing G0. This feature can be built and tested against doubles without it,
  and cannot be believed without it.

## Constraints that are not negotiable

- `AGENTS.md`, the non-negotiable safety boundary, in full. In particular the
  application order adapter is the only order path, and an LLM may not size,
  select, or improvise an order.
- `.claude/rules/30-execution.md` bullet 2 requires a time-limited human arm
  plus a deterministic risk approval bound to the canonical payload and frozen
  config hashes; its bullet 5 makes broker truth outrank local state and
  requires unexplained state to disarm new entries; its bullet 8 forbids
  presenting emergency flatten as guaranteed liquidation.
  `.claude/rules/01-safety.md` bullet 4 requires a fail closed halt on any
  uncertainty, and its bullet 1 forbids a live host, a live credential path, or
  a generic `paper=false` switch.
- D-001 paper only, D-006 the agent MCP stays market-data-only, D-017 an
  uncommitted threshold may not be invented in code, D-023 the client order id
  is derived before the approval exists.
- The merged `PaperTransport` Protocol types `follow_redirects` as
  `Literal[False]`, so a caller cannot ask to follow a redirect. Stated
  precisely, because an earlier draft of this spec overstated it: that typing
  constrains callers at type check time and constrains nothing about what an
  implementation's body does at run time. The implementation must therefore be
  tested for the behaviour, not assumed to have it, which is criterion 12.

## Success criteria

1. No live host string, live credential path, or mode switch exists anywhere in
   the feature. Falsified by any grep for the live trading host that matches
   outside a test asserting its rejection.
2. A credential never reaches a log line, a ledger entry, an exception message,
   or a stack frame that is recorded. Falsified by a test that arms with a
   sentinel secret and finds it in any recorded artifact. This spans two units,
   so the boundary is named rather than left to fall between them: the client
   raises no exception carrying a credential, and the orchestrator records no
   entry carrying one. Both halves are testable in their own unit, and the
   sentinel test runs against the composed path.
3. The transport cannot be called without an unexpired arm record, because the
   submit path takes a value only an arm read can produce, in the shape
   UNIT-012 already uses for `RecordedSubmissionAttempt`. Falsified by any
   reachable call to the transport constructed without one, and by any code
   path that obtains one other than by reading a live arm record. An `if` guard
   is not this criterion; a guard can be forgotten at one call site, which is
   the failure mode the type shape removes.
4. An expired arm blocks submission with the same force as no arm. Falsified by
   a submission accepted one instant after expiry.
4a. Arming requires the human to supply the configuration hash the tool
   displayed, and a supplied hash that does not match the currently committed
   configuration refuses to arm. Falsified by an arm that succeeds without the
   hash, or one that succeeds after the configuration changed between the two
   steps. This is what makes the record a statement about limits a human read,
   rather than proof that a command was run.
4b. Every invocation recomputes the frozen configuration hash and compares it
   to the one recorded in the arm. A mismatch disarms and refuses to trade
   until a human arms again. Falsified by an invocation that trades under a
   configuration differing from the armed one. Design section 15 requires this,
   the two step arm closes only the window before an arm exists, and an earlier
   draft asserted the property in Assumptions with nothing building it.
5. Disarm takes effect before the next submission because the arm record is
   read from its durable store immediately before the transport call, not once
   per invocation and cached. Falsified by an order submitted after a disarm
   returned, and by any submit path that reads the arm earlier than the call it
   authorises. Stated as a mechanism because an earlier draft said only "with
   no in-flight exception", which two implementers would build differently: one
   rereading per submission and one reusing a value fetched at invocation
   start, and only the first is disarmable while a scan is running.
6. Every session transition in design section 11 is recorded in the ledger,
   including entry into halted and every no-trade. Falsified by a transition
   observable in the state machine and absent from the ledger.
7. A process killed between deriving a client order id and receiving a response
   restarts, resolves the ambiguity by querying broker truth, and never submits
   a second intent for that decision. Falsified by two broker orders carrying
   one derived id.
8. The session refuses new entries while any order state is unknown, and states
   which order and why. Falsified by an entry accepted while an unresolved
   submission exists.
9. One MLeg order completes submit, observe, cancel or fill, reconcile, and
   exit against a recorded fake broker that replays real Alpaca response
   shapes. The evidence is the ledger the run itself writes plus the test
   output, not a separate transcript some unit would have to produce; an
   earlier draft asked for "the exact commands and their output recorded" and
   named nothing that produces such an artifact. Falsified by any
   step that was inspected rather than run. This is what done means for this
   feature, and it does not wait on G0.
9a. The same sequence completes against the competition paper account. This is
   the G1 gate criterion, not a criterion of this feature, and it is
   unreachable until G0 clears. It is listed here so the boundary is explicit:
   an earlier draft folded it into criterion 9, which would have made this
   feature permanently unfinishable by its own definition while G0 stayed
   open.
10. Tests do not require network access. Falsified by a suite that fails with
    no route to the broker.
11. No import of `alpaca.trading` exists anywhere in the source tree, and no
    string equal to the live trading host appears outside a test asserting its
    rejection. Falsified by either appearing. This is stronger than asking a
    read client not to write, and it is stated this way because the weaker form
    was tried first and the library defeated it.
12. The transport does not follow a redirect at run time. Falsified by a
    stubbed server answering 3xx with a Location the transport then requests.
    The Protocol's typing does not establish this; only the test does.
13. Manual flatten and emergency halt run as their own invocations a human
    starts at any moment, not as work the scheduled scan performs when it next
    wakes. Falsified by either being reachable only from inside a scheduled
    run. Under an invocation model there may be no process alive between scans,
    so "immediately" can only mean "a human can start one now", and an earlier
    draft of this criterion assumed a running loop that could be interrupted.
14. A session killed at any point, including between a ledger write and its
    next action, reconstructs to a state that agrees with broker truth, or
    refuses to trade and says which fact it could not establish. Falsified by a
    reconstruction that silently differs from the broker in any order or
    position, not only in the ambiguous submit case criterion 7 covers.
## Assumptions

The orchestrator composes the merged units and adds no trading logic of its
own. Sizing stays in UNIT-013, structure selection in UNIT-014, reconciliation
in UNIT-015, exits and flatten in UNIT-017, and rung prices in UNIT-019.

The session machine and the per-order machine stay separate, as UNIT-012's
intake already requires. An order reaching a terminal state is an event the
session observes, not a session state.

The arm binds to the frozen configuration hash UNIT-004 computes, so editing a
committed threshold during a session invalidates the arm rather than silently
changing the rules under it. `config/risk.toml`'s own header already states
this intent.

A no-trade session is a success, not a failure, and produces a complete
evidence trail. This is stated because a feature described as "the trading
session" invites the opposite assumption.

## Clarifications

### 2026-08-31

- Q: The merged `PaperTransport` Protocol is shaped `request(url, body,
  follow_redirects)`, which `alpaca-py` does not satisfy, and routing orders
  through the SDK would bypass UNIT-010's endpoint assertion. How is the
  transport built?
- A: Split. `alpaca-py` for reads, meaning account, positions, activities, and
  the clock, where no order risk exists. Raw HTTP behind the merged
  `PaperTransport` Protocol for anything that places, cancels, or replaces an
  order. The order path keeps one assertion and one client.

  The cost accepted, recorded because it is real: two auth paths, two error
  models, and two retry policies, one of them on the order path. The read side
  gets a maintained library for schema and pagination; the write side stays
  hand rolled and reviewed here.

  The consequence that needs a mechanism rather than a note: `alpaca-py`'s
  trading client is capable of placing orders. Introducing it for reads puts
  that capability back inside the application, which is exactly what D-006
  removed from the coding agent's MCP connection and for exactly the same
  reason. The read client must therefore be narrowed by construction, not by
  convention, and criterion 11 is the falsifiable form of that.

- Q: Is the orchestrator a long lived process holding the session, or scheduled
  invocations that rebuild it each time?
- A: Scheduled invocations. Each one loads the arm record, reconciles against
  the broker, rebuilds session state from the ledger, acts, and exits.

  The reason is not simplicity, it is test coverage of the path that matters.
  In a long lived process the restart path runs only after a crash, which makes
  it the least exercised code in the system at exactly the moment it is load
  bearing. Here reconstruction is the only path there is, so it runs on every
  scan and a defect in it surfaces immediately rather than during an incident.

  Two consequences follow and both are requirements, not observations. The arm
  state must be durable and time limited, because it outlives every process
  that reads it, which is what the remaining open question is about. And the
  ledger becomes the source of session truth rather than a record of it, so a
  transition that is not written is a transition that did not happen as far as
  the next invocation can tell. Criterion 6 already requires every transition
  to be recorded; under this shape that criterion is what makes the system
  work, not merely what makes it auditable.

- Q: What must the arming action prove about human intent?
- A: That the human read the specific limits they armed. The tool displays the
  frozen configuration hash and the limits it implies, and arming requires that
  hash to be passed back. A single command that computed the hash itself was
  rejected: it proves a command was run, not that anyone agreed to these
  numbers, and the whole point of an arm is that it is the one moment a human
  takes responsibility for what follows. A two person arm was rejected as wrong
  for a two person team, since it makes a solo session impossible.

  This also closes the configuration drift question by construction. A hash
  supplied from a display taken before an edit will not match after it, so
  editing `config/risk.toml` between the two steps refuses rather than arms
  silently. That is the behaviour `config/risk.toml`'s own header already
  claims.

  Decided rather than asked, following UNIT-005's precedent: the arm's maximum
  lifetime is a committed value in `config/risk.toml`, hashed with everything
  else, not a constant in code and not a caller supplied parameter. D-017
  requires it to be committed to be auditable, and UNIT-005 has just
  demonstrated the shape. It expires at or before the end of one trading
  session, so an arm cannot survive unattended into a day nobody intended.

- Q: `alpaca-py`'s `TradingClient` takes `paper: bool = True` resolving to the
  live host, which `.claude/rules/01-safety.md` forbids outright, and it has no
  account activities method. Does the read side SDK decision stand?
- A: No, it is superseded. `alpaca-py` is admissible for market data only, where
  its clients take no paper argument and resolve to a data host that cannot
  accept an order. Every account, position, activity, and clock read moves onto
  the merged `PaperTransport` Protocol alongside the order path.

  Recorded because it is the more useful half: the option this replaces was
  offered without reading the library, and the library was checked only when an
  independent analysis pass read its installed source.
  `alpaca/trading/client.py` line 58 takes `paper: bool = True`, line 82
  resolves it as `BaseURL.TRADING_PAPER if paper else BaseURL.TRADING_LIVE`,
  and `TRADING_LIVE` is the literal live host. Adopting that client would have
  imported the exact switch UNIT-010 exists to make impossible, which is why
  criterion 11 is now about imports and strings rather than about a client's
  good behaviour.

  The split now falls on a real boundary rather than a convenience one: a
  library that cannot reach a trading host is used where it cannot cause harm,
  and everything that can reach one goes through the single asserted path.
  UNIT-028 in the research lane will want those same data clients regardless.
