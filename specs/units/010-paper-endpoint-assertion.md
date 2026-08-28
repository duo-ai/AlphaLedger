---
id: UNIT-010
title: Assert the paper endpoint and make live impossible
lane: execution
state: claimed
owner: pablo/codex
branch: feature/010-paper-endpoint-assertion
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-001]
paths: src/alphaledger/broker/**, tests/execution/**
claimed_at: 2026-08-28T17:54:19Z
---

## Problem

Every other execution unit assumes it cannot reach live money. Nothing enforces
that yet. A configuration typo, an environment variable, or a redirect could
point the adapter at the live host, and no later gate would catch it because
every later gate trusts this one.

## Source of truth

- `AGENTS.md`, non-negotiable safety boundary.
- `.claude/rules/01-safety.md` and `.claude/rules/30-execution.md`.
- `project-state/DECISIONS.md` D-001.
- `hackathon-build-plan.md` section 4, the 15:00 to 16:00 block.

## Scope

In:

- A single resolver that returns the trading base URL and refuses to return
  anything other than `https://paper-api.alpaca.markets`.
- Assertion at process start and again immediately before any submit call.
- Refusal of redirects to another host.
- A startup banner recording the resolved host, without printing credentials.

Out:

- Order construction and submission (UNIT-011, UNIT-012).
- Account and position reads (UNIT-015).

## Contract

`alphaledger.broker.endpoint.resolve_paper_base_url() -> str` returns the
paper host or raises `LiveEndpointError`. There is no parameter, environment
variable, or configuration key that makes it return another host. There is no
`paper: bool` flag anywhere in the signature, because a boolean is a thing that
can be set to `False`.

## Acceptance criteria

- AC-1: the resolver returns the paper host on a clean environment.
- AC-2: setting any environment variable to the live host still yields the
  paper host or raises. It never returns the live host.
- AC-3: a redirect response pointing at another host raises before any payload
  is sent.
- AC-4: a grep of `src/` finds no occurrence of the live host outside a test
  fixture and no `--live` code path.
- AC-5: the assertion runs again immediately before submit, not only at start.

## Test list

- success: resolver returns the paper host and the recorded banner names it.
- success: the pre-submit assertion passes and the call proceeds.
- failure: an environment variable naming the live host raises
  `LiveEndpointError` and the message does not contain any credential value.
- failure: a 302 to another host raises before the request body is sent.
- failure: a configuration object mutated after start to a live host is caught
  by the pre-submit assertion, not only the startup one.
- restart: the assertion runs on every process start, so a restart cannot
  inherit a previously validated host from local state.
- no-trade: when the assertion fails the system halts and records the reason
  rather than falling back to a default host.

## Verification

```bash
uv run pytest tests/execution/test_endpoint.py -q
uv run ruff check . && uv run mypy src
```

## Handoff notes
