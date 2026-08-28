---
id: UNIT-011
title: Map Alpaca order schemas behind a typed adapter
lane: execution
state: claimed
owner: pablo/codex
branch: feature/011-order-schema-adapter
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-001, UNIT-010]
paths: src/alphaledger/execution/__init__.py, src/alphaledger/execution/orders.py, tests/execution/test_orders.py
claimed_at: 2026-08-28T22:06:35Z
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
```

`BrokerOrder` is frozen and carries the broker id, the client order id, a
status, filled quantity, and timestamps. Its status is an enum that includes an
explicit `unknown` member.

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
- failure: a payload whose hash was computed, then a leg mutated, produces a
  different hash. This is the property `RiskApproval` depends on.
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
