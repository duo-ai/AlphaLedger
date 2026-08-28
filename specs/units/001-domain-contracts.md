---
id: UNIT-001
title: Freeze the domain contracts
lane: shared
state: claimed
owner: pablo/claude
branch: feature/001-domain-contracts
reviewer: code-reviewer
preferred_runtime: codex
depends_on: []
paths: src/alphaledger/domain/**
claimed_at: 2026-08-28T16:48:52Z
---

## Problem

Both lanes consume and produce the same five domain objects. Until they exist
as one frozen module, the execution lane and the research lane will each invent
their own shape for `Forecast` and `EvidenceCard`, and every merge will conflict
on the definitions rather than on behaviour. Nothing else can be claimed until
this is merged.

## Source of truth

- `options-alpha-agent-design.md` section 14 for the five dataclasses, verbatim.
- `options-alpha-agent-design.md` section 4 for the timestamp contract fields.
- `.claude/rules/10-python.md` for typing, UTC, and `Decimal` rules.

## Scope

In:

- The Python project itself, because nothing here can be verified without it:
  `pyproject.toml` with `requires-python = ">=3.14"`, a committed `uv.lock`,
  the `src/` and `tests/` layout, and the ruff, mypy, and pytest configuration
  named in the quality gate in `AGENTS.md`.
- `NewsLabel`, `EvidenceCard`, `Forecast`, `StructurePlan`, `RiskApproval` as
  frozen dataclasses.
- The money and quantity types used across the boundary, with declared rounding.
- The observation timestamp tuple: `event_time`, `first_seen_time`,
  `source_time`, `received_time`, `feed`, `as_of`.
- Construction-time validation that rejects a naive datetime and a float where
  money is required.

Out:

- Anything that reads a broker, a feed, or a model. This module has no I/O and
  no dependency on any other `alphaledger` package (UNIT-011, UNIT-020).
- Persistence and serialisation formats (UNIT-016).

## Contract

A single package, `alphaledger.domain`, importable with no side effects and no
network. Every type is immutable and hashable. Money, prices, strikes, and
payoffs are `Decimal`; quantities are `int`. All datetimes are timezone-aware
UTC and are rejected otherwise.

## Acceptance criteria

- AC-1: the five dataclasses match design section 14 field for field, including
  names, types, and `Literal` members.
- AC-2: constructing any type with a naive datetime raises, naming the field.
- AC-3: constructing a money or price field from `float` raises. `Decimal` and
  `str` are accepted; `str` is parsed exactly.
- AC-4: instances are frozen. Mutating any field raises.
- AC-5: importing `alphaledger.domain` performs no I/O and imports no adapter,
  broker, or model package.
- AC-6: `uv sync --frozen` succeeds on 3.14 and each command in the quality
  gate runs. `requires-python` is `>=3.14`, so the interpreter is pinned where
  it is enforced rather than only where it is described.

## Test list

- success: each of the five types constructs from a valid payload and compares
  equal to an identically constructed instance.
- success: an observation carrying all six timestamp fields round-trips without
  losing UTC offset.
- failure: a naive `event_time` raises and the message names `event_time`.
- failure: `exact_max_loss` given a `float` raises rather than silently
  converting.
- failure: assigning to a field on a constructed `RiskApproval` raises.
- restart: a `RiskApproval` rebuilt from its recorded field values hashes equal
  to the original, so an approval survives a process restart without becoming a
  new intent.
- no-trade: a `Forecast` with `eligible=False` and a populated
  `rejection_reasons` is valid and constructible. A no-trade is a first-class
  result, not an error path.

## Verification

```bash
uv run pytest tests/domain -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
