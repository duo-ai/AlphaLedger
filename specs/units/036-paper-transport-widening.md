---
id: UNIT-036
title: Widen the paper transport to carry a verb and a response body
lane: execution
state: claimed
owner: mazwy/claude
branch: feature/036-paper-transport-widening
reviewer: execution-safety-reviewer
preferred_runtime: claude
depends_on: [UNIT-001, UNIT-010]
paths: src/alphaledger/broker/endpoint.py, tests/execution/test_endpoint.py
claimed_at: 2026-09-04T12:53:35Z
---

## Problem

This unit exists because of C1, the finding that invalidated the centre of the
feature 001 plan. It is recorded in
`specs/features/001-autonomous-session/analysis-codex.md`.

`PaperTransport`, merged by UNIT-010, is

```python
def request(self, url: str, body: bytes, *, follow_redirects: Literal[False]) -> TransportResponse
```

and `TransportResponse` carries `status_code` and `location` and nothing else.
There is no HTTP method and no response body, so the one asserted path can send
something and learn only whether it was redirected. It cannot perform a GET and
it cannot return anything to parse.

Every operation the order path needs uses a distinct verb: submit is POST,
order and account lookup are GET, replace is PATCH, cancel is DELETE. Five
analysis passes read this file and none noticed, because the omission only
becomes a defect when held against a contract that promises parsed reads.

An implementer of UNIT-031 has exactly two ways forward without this unit, and
both are forbidden. Adding `httpx` calls beside the Protocol creates a second
order path that skips UNIT-010's endpoint assertion, which `AGENTS.md` forbids
outright. Editing `endpoint.py` from inside UNIT-031 writes outside that unit's
declared globs, which D-010 forbids. So the contract is widened here, in its
own unit, and the feature spec's Out list permits this one change to a merged
unit and no other.

## Source of truth

- `specs/features/001-autonomous-session/analysis-codex.md`, finding C1.
- `src/alphaledger/broker/endpoint.py` as merged by UNIT-010, and
  `tests/execution/test_endpoint.py`.
- `specs/units/010-paper-endpoint-assertion.md`, whose acceptance criteria this
  unit must leave standing. In particular: no `paper: bool` exists anywhere,
  because a boolean can be set to `False`.
- `.claude/rules/01-safety.md` and `.claude/rules/30-execution.md`.

## Scope

In:

- an `HttpMethod` type admitting exactly `GET`, `POST`, `PATCH`, and `DELETE`;
- that method as a required argument on `PaperTransport.request` and on
  `send_paper_request`, positioned so an existing call cannot silently keep
  compiling with the wrong verb;
- a response body on `TransportResponse`, as raw `bytes`, so a caller can parse
  a read;
- permitting a query string on the request path, since every GET the order path
  needs carries one, while keeping the existing rule that a path is relative.

Out:

- the concrete HTTP client. That is UNIT-006 and UNIT-031. This unit adds no
  dependency and imports nothing new.
- parsing. `TransportResponse.body` is bytes and this unit never decodes it.
  Deciding what a payload means belongs to UNIT-011's schema adapter.
- retries, timeouts, and connection reuse, which are properties of the concrete
  client behind the Protocol.
- widening anything else about the boundary. The endpoint assertion, the
  redirect rejection, and the indeterminate-response raise are preserved
  exactly, and this unit narrows nothing and permits no new host.

## Contract

`alphaledger.broker.endpoint`:

- `HttpMethod = Literal["GET", "POST", "PATCH", "DELETE"]`. No other verb is
  expressible. There is deliberately no `PUT` and no arbitrary string.
- `TransportResponse` gains `body: bytes`, defaulting to `b""` so a transport
  that has nothing to return is still constructible. `status_code` and
  `location` are unchanged, and `body` is `repr=False` like `location`, because
  a broker payload in a traceback is a disclosure risk.
- `PaperTransport.request(self, method: HttpMethod, url: str, body: bytes, *,
  follow_redirects: Literal[False]) -> TransportResponse`. `method` is first,
  not keyword-only and not defaulted: every existing implementation and call
  site must be updated by the compiler rather than by inspection, and a default
  would let a PATCH be sent as whatever the default was.
- `send_paper_request(configuration, method, path, body, transport, recorder)`
  passes the verb through unchanged and returns the response including its
  body.
- The relative-path rule stands and now admits a query string: a path must
  start with a single `/`, and `?` and `&` are permitted after that.

## Acceptance criteria

- AC-1: each of the four verbs reaches the transport exactly as supplied, and
  no other value is expressible. Falsified by a recording transport observing a
  verb other than the one passed.
- AC-2: the response body reaches the caller unchanged, byte for byte, for a
  GET. Falsified by a transport returning a known payload and the caller
  receiving something else, including a decoded string.
- AC-3: the paper endpoint assertion still runs on every request, for every
  verb. Falsified by a configuration carrying a non-paper base URL reaching the
  transport under any verb.
- AC-4: a 3xx still raises `IndeterminateResponseError` and still records the
  no-trade reason, under every verb, not only the verb the original test used.
  Falsified by a redirect returning normally for a GET.
- AC-5: an absolute or protocol-relative path is still refused, and a path
  carrying a query string is accepted. Falsified by either half.
- AC-6: no `paper: bool`, mode flag, or live host string exists anywhere in the
  module after the change. Falsified by grep, and this is UNIT-010's own
  criterion restated because this unit is the one that could break it.
- AC-7: a GET may carry an empty body without special-casing. Falsified by a
  raise on `b""`.

## Test list

- success: each of the four verbs is passed through to the transport and
  observed (AC-1).
- success: a GET returns a body byte for byte, including bytes that are not
  valid UTF-8, so nothing decodes on the way through (AC-2).
- success: a path carrying a query string is accepted and forwarded intact
  (AC-5).
- success: a GET with an empty body is accepted (AC-7).
- failure: a non-paper base URL is refused under each of the four verbs, not
  only POST (AC-3).
- failure: a 3xx raises `IndeterminateResponseError` under each verb and
  records the reason (AC-4).
- failure: an absolute path and a protocol-relative path are both still refused
  (AC-5).
- restart: the module holds no state, so a second call with the same arguments
  behaves identically; the endpoint is re-resolved per request rather than
  cached across one.
- no-trade: every refusal above records a no-trade reason through the recorder
  rather than only raising.

## Verification

```bash
uv run pytest tests/execution/test_endpoint.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest
```

The full suite matters here, though not for the reason this section first
gave. It said UNIT-011 and UNIT-012 call the changed signature. They do not: a
tree wide grep for `send_paper_request`, `PaperTransport`, and
`TransportResponse` returns nothing outside this unit's two files, and
`src/alphaledger/broker/` holds only `endpoint.py` and `__init__.py`. That is
consistent with `STATUS.md`, which records that no transport submits anything.
Corrected on round one by `execution-safety-reviewer`. A false claim that a
change is risky is safer than the reverse, but it is still false, and a later
reader would infer coupling that does not exist.

The declared paths were also narrowed on round one, from
`src/alphaledger/broker/**` to the single file this unit actually changes. The
wide glob was not harmless: `coord.py` refuses a claim overlapping an
in-flight unit, so it reserved the whole broker package and would have blocked
UNIT-031, whose own file sits beside this one. It also turned a
`verify_harness.sh` probe red, because that probe makes merged UNIT-010
claimable and UNIT-010 declares exactly the files this unit had swallowed.

## Handoff notes
