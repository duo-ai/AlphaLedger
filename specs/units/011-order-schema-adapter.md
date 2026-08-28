---
id: UNIT-011
title: Map Alpaca order schemas behind a typed adapter
lane: execution
state: in_review
owner: pablo/codex
branch: feature/011-order-schema-adapter
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-001, UNIT-010]
paths: src/alphaledger/execution/__init__.py, src/alphaledger/execution/orders.py, tests/execution/test_orders.py
claimed_at: 2026-08-28T22:06:35Z
reviewed_by: execution-safety-reviewer
review_verdict: block
reviewed_at: 2026-08-28T23:42:34Z
review_log: [block, block]
---

## Problem

A `StructurePlan` describes a trade in our vocabulary; Alpaca wants an `mleg`
order in its own. Nothing translates between them, and nothing produces the
`order_payload_hash` that `RiskApproval` already carries a field for. Until one
module owns that mapping in both directions, every later unit will invent its
own encoding, and the risk approval will be bound to a payload nobody can
reproduce.

## Source of truth

- `options-alpha-agent-design.md` section 11, entry step 3, and the integration
  caveat that follows it.
- `options-alpha-agent-design.md` section 8 for the debit-vertical shape and the
  limit-price conventions.
- `orchestrator-system-prompt.md`, the order-adapter paragraph.
- `.claude/rules/30-execution.md`, bullets 1, 2 and 6.
- `project-state/DECISIONS.md` D-006, which is why the direct Trading API
  mapping is the only path.

## Scope

In:

- The forward mapping: a `StructurePlan`, an approved quantity, and an approved
  limit price become a canonical Alpaca `mleg` request. `order_class` is
  `mleg`, time in force is `day`, type is `limit`, and the legs are an array.
- Canonical serialization to `bytes`. Keys sorted, `Decimal` rendered as a
  string, no float anywhere in the output. The same inputs must produce
  byte-identical output in a different process.
- `order_payload_hash(payload) -> str`. This is the value `RiskApproval`
  binds to. It exists in the merged contracts with nothing producing it, so
  this unit is its producer. If a later unit invents a second scheme the
  binding becomes decorative.
- The declared leg key vocabulary. Design section 14 leaves the leg schema
  open, so this unit fixes it and every other unit follows.
- The debit and credit sign convention, as a single named constant with a test
  that pins it, so a Day-0 correction is a one-line change rather than an
  archaeology exercise.
- The inverse mapping: a raw Alpaca order, activity, or position payload
  becomes a typed frozen record.

Out:

- Endpoint assertion, URL construction, and redirect handling. UNIT-010 owns
  those and this unit calls `send_paper_request`. Re-implementing any of them
  is the most likely way this unit breaks the D-001 boundary.
- `client_order_id` derivation and every order state (UNIT-012).
- Choosing the limit price or stepping a ladder (UNIT-013).
- Building legs from a real chain, and the `D<=0` or `D>=W` invalidity rules
  (UNIT-014). This unit maps whatever plan it is given and does not re-derive
  the payoff.
- The scheduled reconcile loop (UNIT-015).

## Contract

`alphaledger.execution.orders`, importing from `alphaledger.domain` and
`alphaledger.broker.endpoint`, never the reverse.

```python
def build_mleg_order(
    plan: StructurePlan, quantity: int, limit_price: Decimal, client_order_id: str
) -> Mapping[str, object]: ...

def canonical_bytes(payload: Mapping[str, object]) -> bytes: ...
def order_payload_hash(payload: Mapping[str, object]) -> str: ...
def parse_order(raw: Mapping[str, object]) -> BrokerOrder: ...
def parse_activity(raw: Mapping[str, object]) -> BrokerActivity: ...
def parse_position(raw: Mapping[str, object]) -> BrokerPosition: ...
```

`BrokerOrder` is frozen and carries the broker id, the client order id, a
status, filled quantity, and timestamps. Its status is an enum that includes an
explicit `unknown` member.

`BrokerActivity` and `BrokerPosition` are frozen too and live beside
`BrokerOrder` in `orders.py`, which is what this unit's declared globs allow.
They exist because an order alone cannot rebuild truth after a restart: an
ambiguous submit that partially filled is visible as fills and as a held
position, and a reconciler with no typed way to read either has to bypass this
boundary or stay halted. Carry what reconciliation needs and nothing more. For
an activity, its broker id, the id of the order it belongs to, its type, the
symbol, the signed quantity, the price, and the time. The order id is what links
a fill to the intent that caused it; without it, two orders in the same option
are indistinguishable after a restart and a reconciler cannot tell whether
retrying would duplicate one. For a position, the symbol, the signed quantity,
the average entry price, and the side, and a quantity whose sign contradicts the
side is malformed broker truth under AC-5 rather than a record to construct. Quantity is an integer and every price is a
`Decimal`, on the same terms as the rest of this module. Both parsers obey AC-4
and AC-5: an unrecognised enumerated value becomes `unknown` rather than a
default, and a truncated payload raises the typed adapter error.

The serializer accepts `Decimal` and rejects `float`, matching `money()` in the
domain. It must not re-round: the domain already quantizes to four places with
`ROUND_HALF_EVEN`, and a second rounding in the adapter would silently disagree
with the approved plan.

## Acceptance criteria

- AC-1: a plan, quantity and limit price produce a payload with `order_class`
  `mleg`, `time_in_force` `day`, `type` `limit`, and one array entry per leg.
- AC-2: serialization is deterministic. The same inputs produce byte-identical
  output in a separate process, and no `float` appears anywhere in the bytes.
- AC-3: `order_payload_hash` is stable for equal payloads and changes when any
  field changes, including a leg reordering that alters meaning.
- AC-4: an unrecognised broker status parses to `unknown`. It never defaults,
  and it never becomes `rejected`. Treating an unknown result as a rejection is
  how a live order becomes invisible.
- AC-5: a malformed or truncated broker payload raises a typed adapter error,
  not `KeyError` or `TypeError`.
- AC-6: the debit and credit sign convention is one named constant, and a test
  fails if its sign flips.
- AC-7: the module contains no host string, no URL construction, and no
  redirect logic. It reaches the network only through `send_paper_request`.
- AC-8: a leg key outside the declared vocabulary is rejected at build time.
- AC-9: a documented Alpaca activity payload and a documented position
  payload each parse to their frozen record, and a truncated one raises the
  typed adapter error rather than `KeyError`.
- AC-10: the hash property in AC-3 is proven field by field. Mutating any
  single top-level field, and any single leg field, changes the hash. A test
  that mutates one example field cannot tell a complete canonicalization
  from one that silently drops `qty`, `limit_price`, or `client_order_id`.

## Test list

- success: a two-leg debit vertical maps to the expected `mleg` payload, field
  by field, against a hand-written fixture rather than a round trip.
- success: serializing the same payload twice, in separate processes, yields
  identical bytes and an identical hash.
- success: a realistic Alpaca order payload parses to a `BrokerOrder` with the
  expected status and filled quantity.
- failure: a `float` limit price or a `float` inside a leg is rejected, naming
  the field.
- failure: a leg key outside the vocabulary is rejected, naming the key.
- failure: a truncated broker payload raises the typed adapter error and the
  message does not contain any credential-shaped value.
- failure: a payload whose hash was computed, then any single field mutated,
  produces a different hash. Parameterise over every top-level field and
  every leg field rather than one example, including a leg reordering that
  alters meaning. This is the property `RiskApproval` depends on, and a
  single-field version of it stays green while canonicalization drops a
  field that decides size or price.
- success: a realistic Alpaca activity payload and position payload each
  parse to their frozen record with the expected quantity sign and price.
- restart: after an ambiguous submit, the fills reported as activities and
  the resulting position both parse, so a reconciler can reconstruct filled
  quantity from broker truth without leaving the typed boundary.
- failure: a truncated activity payload and a truncated position payload
  each raise the typed adapter error.
- restart: a hash computed in one process equals the hash computed in another
  from the same plan, so an approval survives a restart. Use a subprocess.
- no-trade: an unrecognised status parses to `unknown` and the caller can
  distinguish it from every terminal state, so the lifecycle can fail closed
  rather than assume.

## Verification

```bash
uv run pytest tests/execution/test_orders.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Notes

The MCP multi-leg serialization issue recorded in design section 11 is the
rationale for this unit, not a branch to implement. D-006 omits the trading
toolset from every committed coding-agent MCP configuration, so the direct
Trading API mapping is the only order path. Do not build an MCP-versus-direct
switch; adding one would violate D-006.

`project-state/STATUS.md` lists current MLeg request behaviour as unverified
while G0 is open. So the schema tests here are deterministic fixtures against
the documented shape. Any test that reaches the live API carries the
`paper_integration` marker, which the default run excludes.

## Handoff notes

- 2026-08-29 code review round one, `execution-safety-reviewer` via
  `codex exec review`, verdict block. Two P1 findings.
  1. `src/alphaledger/execution/orders.py` around line 143. The Scope section
     required the inverse mapping for an order, an activity, and a position,
     and only `parse_order` shipped. After an ambiguous submit partially fills
     and the process restarts, activities and positions are what reconstruct
     truth, so reconciliation would have to bypass this typed boundary or stay
     halted, against the startup reconciliation invariant in
     `.claude/rules/30-execution.md`.
  2. `tests/execution/test_orders.py` around line 292. The payload-hash
     mutation test mutates only a leg symbol and its ordering. If
     canonicalization later omits `qty`, `limit_price`, or `client_order_id`,
     an approval hashed for one payload could authorise a changed size or price
     while that test stays green, which leaves AC-3 unprotected.
- 2026-08-29 pablo/claude. The first finding is partly an intake defect, and it
  is fixed above rather than left for the next reader. Scope named orders,
  activities, and positions while the Contract code block listed `parse_order`
  alone, so the unit disagreed with itself and the implementer followed the
  half that was executable. The Contract, the acceptance criteria, and the test
  list now carry all three. This is the same shape as the UNIT-004 contract
  contradiction, and it is the second time an intake I wrote has sent an agent
  at an underspecified surface.
- 2026-08-29 pablo/claude on the package note. The reviewer named Pydantic v2
  as the established alternative to the hand-rolled validation layer, correctly
  applying the package rule in `AGENTS.md`. Not adopting it in this unit: it is
  not currently a dependency, the merged domain layer hand-rolls the same shape
  of validation deliberately, and introducing it here would split the
  validation story across two idioms at the boundary that most needs one. It is
  one decision for the whole boundary, and it is recorded on UNIT-004 too.

- 2026-08-29 code review round two, `execution-safety-reviewer`, verdict block.
  One P1 and one P2, both inside `orders.py`, both on the reconciliation surface
  round one asked for.
  1. P1, `orders.py` around line 116. `BrokerActivity` keeps the activity's own
     id and drops the `order_id` the documented fixture supplies. Under an
     ambiguous submit with a prior or concurrent order in the same option,
     aggregate positions and symbol-only fills cannot say which intent filled,
     so a reconciler cannot tell whether retrying would duplicate an order.
     Preserve and parse it, and test two orders on the same symbol.
  2. P2, `orders.py` around line 242. A position with `qty="-1"` and
     `side="long"`, or a positive quantity with `short`, currently constructs a
     frozen record whose own fields disagree. A restart reconciler then infers
     opposite positions depending on which field it reads. Refuse it under AC-5.
  3. The reviewer also found that
     `test_ambiguous_submit_reconstructs_leg_quantities_from_activities_and_positions`
     reasserts quantities its own fixture configured, so it stays green while
     order correlation is broken. It is the test for the finding above and has
     to change with it.
- 2026-08-29 pablo/claude, on spending a third round. `coord.py` refused to
  reopen this unit without `--another-pass`, which is D-022 working as intended.
  The round is justified: both findings are inside the unit's declared globs,
  the first bears on AC-9 and on the restart path AC-5 governs, and the second
  is AC-5 directly. The first is also partly an intake defect again. My Contract
  paragraph listed what an activity should carry and omitted the order id, which
  is the one field the reconciliation story depends on. That is fixed above.
- 2026-08-29 pablo/claude, scope for round three. These two findings and the
  test that goes with them are the whole of it. The reviewer's list of arm
  expiry, risk and config binding, sizing, idempotency, timeout lookup, complete
  reconciliation, staleness, exits and flattening, and ledger behaviour belongs
  to UNIT-012 onward. It is not in scope here and must not be implemented here.

