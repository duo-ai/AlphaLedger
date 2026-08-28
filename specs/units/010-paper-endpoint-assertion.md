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
paths: src/alphaledger/broker/**, tests/execution/test_endpoint.py
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
- AC-3: redirect following is disabled at the transport, and a cross-host
  redirect response is rejected without any replay to the redirect target.
  Correction from review: a redirect is a response, so the payload has
  necessarily already been sent when one arrives. "Before any payload is
  sent" was not achievable and the original wording was wrong. The real
  guarantee is no replay. UNIT-011 must additionally prove, against the
  concrete transport it ships, that automatic following is genuinely
  disabled at the library level rather than merely unobserved by a mock.
- AC-4: a grep of `src/` finds no occurrence of the live host outside a test
  fixture and no `--live` code path.
- AC-5: the assertion runs again immediately before submit, not only at start.
- AC-6: `EndpointConfiguration` is frozen and constructible only through a
  factory bound to the resolver, so a non-paper `base_url` is a type error
  rather than something a later runtime check must catch. A bare mutable
  `str` field carries the same risk as the `paper: bool` this unit refused.
- AC-7: every public entry point that can reject records a no-trade reason.
  A direct `resolve_paper_base_url()` failure must not leave the ledger
  silent just because it skipped the wrapper.
- AC-8: rejection reasons are distinct per cause. A non-paper host, a
  malformed request path, and a malformed redirect must be
  distinguishable in the ledger.
- AC-9: `base_url` and redirect `location` never appear in a `repr`. The
  existing protection covers `str(exc)` only, so a log line or a test diff
  rendering one of these objects would still leak the value.

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
- no-trade: a direct `resolve_paper_base_url()` failure, not routed through
  `validate_process_start`, still records its reason.
- failure: a rejected redirect, a malformed path, and a non-paper host each
  record a different reason code.
- failure: `repr()` of a configuration or response carrying a token-bearing
  value does not contain the value. Assert on `repr`, not only `str(exc)`.
- failure: constructing a configuration with a non-paper host is impossible
  outside the resolver-bound factory.
- restart: a fresh interpreter, not only an in-process re-invocation,
  re-runs the assertion. Use a subprocess, so a module-level cache added
  later cannot hide behind an in-process test.

## Verification

```bash
uv run pytest tests/execution/test_endpoint.py -q
uv run ruff check . && uv run mypy src
```

## Handoff notes

## Review findings, 2026-08-28

`execution-safety-reviewer` returned conditional on the first implementation.
AC-3 was unsatisfiable as originally worded and has been corrected rather than
forced. AC-6 through AC-9 come directly from the findings.

One test was theatre: the cross-host redirect test asserted that
`send_paper_request` issued no second call, using a recording transport
structurally incapable of following a redirect. It would pass even when the
real failure occurred. Replace it with a test that constrains the transport
contract itself.

Deferred to UNIT-011 and recorded here so it is not lost: a repository-wide
test that fails if any Alpaca client construction or base-URL environment read
appears outside this module, and confirmation from `alpaca-docs-researcher`
that the shipping SDK does not read its own base-URL variable independently of
this resolver.
