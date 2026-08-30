---
id: UNIT-028
title: Fetch Alpaca bars and news into point-in-time records
lane: research
state: available
owner: -
branch: -
reviewer: alpaca-docs-researcher
preferred_runtime: codex
depends_on: [UNIT-001, UNIT-020, UNIT-022, UNIT-023, UNIT-030]
paths: src/alphaledger/data/alpaca.py, src/alphaledger/data/pagination.py, tests/research/test_alpaca_adapter.py, tests/research/test_pagination.py
---

## Problem

Nothing in this repository has ever fetched anything. Eight research units are
merged, every timestamp rule and feature value is proven against fixtures, and
`project-state/STATUS.md` has said "no real feed is connected anywhere" through
four checkpoints. The reason is structural rather than neglect: UNIT-020
records an observation once it exists, UNIT-011 maps order schemas in the
execution lane, and no row owned the path from Alpaca into a point-in-time
record. Every research unit needed it and none of them could build it.

The work is not a thin HTTP wrapper. D-024 read the published schemas and found
four defaults that are wrong for this project, each of which corrupts research
silently rather than failing: unadjusted prices, symbol mapping that reflects
today rather than the decision date, floating point prices the domain contract
refuses, and pagination that can return one symbol where a whole panel was
requested. An adapter written without those four in mind produces data that
looks well formed and is wrong in ways no downstream check can see.

## Source of truth

- `project-state/DECISIONS.md` D-024, which records the schemas and the four
  defaults, and states that it was read from the API reference and never
  confirmed against a live payload.
- `options-alpha-agent-design.md` section 4 for the point-in-time contract and
  section 5.2 for the news source.
- `.claude/rules/20-research-integrity.md` and `.claude/rules/01-safety.md`.
- `src/alphaledger/domain/contracts.py`, `ObservationTimestamps` and `money`.
- `src/alphaledger/data/recorder.py`, merged by UNIT-020.
- `src/alphaledger/evidence/price_volume.py` `Bar` and
  `src/alphaledger/evidence/news.py` `Article`, the two records this adapter
  must produce.

## Scope

In:

- a market-data client behind a small interface, so every test runs without
  network access;
- explicit `adjustment` and `asof` on every bar request, with no reliance on
  either default;
- exhaustive pagination with per-symbol coverage assertions;
- mapping an Alpaca bar to `Bar` and an Alpaca news article to `Article`,
  including the string path into `Decimal` that `money` requires;
- deriving `first_seen_time` from a documented feed lag, per the obligation
  UNIT-020's D-014 hands the adapter;
- treating a revised article as a second observation rather than an edit.

Out:

- order placement, account access, and anything in the execution lane. This
  adapter is market-data-only and must not import from `broker` or `execution`.
- the LLM labeler and its caching (UNIT-029).
- feature construction (UNIT-022, UNIT-023) and the recorder itself
  (UNIT-020). This unit produces records and hands them over.
- a real-time streaming subscription. Historical fetch only; streaming is a
  separate transport with a separate failure model.

## Contract

`alphaledger.data.alpaca.MarketData` is a `Protocol` with `bars(...)` and
`news(...)`, so the pipeline is exercisable against a recorded fixture and
never a live call.

`alphaledger.data.alpaca.fetch_bars(client, symbols, start, end, asof,
config) -> tuple[Bar, ...]` requests an explicit adjustment and an explicit
`asof`, follows pagination to exhaustion, and returns bars for every requested
symbol or raises.

`alphaledger.data.alpaca.fetch_news(client, symbols, start, end, config) ->
tuple[Article, ...]` maps articles, deriving `article_id` from the integer id
and `first_seen_time` from `created_at` plus the configured lag.

`alphaledger.data.pagination.exhaust(page_fn, token_of, items_of) ->
tuple[object, ...]` is the shared loop, with a bounded page count so a server
returning a self-referential token cannot spin forever.

`AdapterConfig` holds `adjustment`, `feed`, `news_lag`, `bar_lag`,
`max_pages`, and derives a content hash so a run manifest can record exactly
which feed and adjustment produced a record.

Errors: `IncompleteCoverageError` when a requested symbol returned no bars and
the caller did not say that was acceptable; `PaginationLimitError` when
`max_pages` is exhausted; `UnusableRecordError` when a payload cannot be mapped
without inventing a value.

## Assumptions

`adjustment` defaults to `all` in `AdapterConfig` and is always sent
explicitly. D-024 gives the reasoning: a cash dividend is a real price drop on
a known date that carries no information about the company, so leaving it in
would place a scheduled negative residual in every label on that date.

`asof` is a required argument rather than a defaulted one. A default is what
makes the point-in-time error easy, and this is the one parameter where the
convenient value is the wrong one.

Prices cross into `Decimal` through `str`, never through `float`. `money`
rejects `float` outright, so this is the domain contract's requirement rather
than a preference.

A revised article, one whose `updated_at` exceeds its `created_at`, is recorded
as a distinct observation keyed by both timestamps. D-014 already says a later
revision is a different observation; this makes that concrete for the one feed
known to revise.

The adapter records what it fetched and does not decide whether it is enough.
An empty result for a symbol is a fact for the recorder and the universe
builder to weigh, except where coverage was explicitly required, which is why
`IncompleteCoverageError` is opt-in rather than automatic.

No credential is read, logged, printed, or placed in an error message. The
client holds its own auth and this module never sees it.

## Acceptance criteria

- AC-1: every bar request sends an explicit `adjustment` and an explicit
  `asof`, and a request built without either raises rather than defaulting.
  Falsified by a recorded request whose query string omits one.
- AC-2: pagination continues until the token is exhausted, and a multi-symbol
  request whose first page holds one symbol still returns every symbol.
  Falsified by a fake client returning three pages and observing only the first
  page's symbols in the result.
- AC-3: a repeated or self-referential page token raises
  `PaginationLimitError` rather than looping. Falsified by a client returning
  the same token forever and observing the call not return.
- AC-4: a price crosses into `Decimal` without passing through `float`.
  Falsified by feeding a payload whose price cannot be represented as a binary
  float and observing a value that differs from the decimal string.
- AC-5: `first_seen_time` is `created_at` plus the configured lag for news and
  the bar timestamp plus the configured lag for bars, and never a clock read.
  Falsified by running the same fixture twice and observing different values.
- AC-6: an article whose `updated_at` exceeds its `created_at` produces a
  record distinguishable from one where they are equal, rather than silently
  overwriting. Falsified by observing one record where two observations exist.
- AC-7: a requested symbol that returned nothing raises
  `IncompleteCoverageError` when coverage was required and is absent from the
  result without raising when it was not. Falsified by observing the same
  behaviour in both modes.
- AC-8: no credential value appears in any exception message, log line, or
  repr. Falsified by constructing a client with a marker secret and searching
  the raised text for it.
- AC-9: `AdapterConfig`'s hash changes when the adjustment or the feed changes,
  so a run manifest can prove which produced a record. Falsified by changing
  one and observing the hash hold.
- AC-10: the module imports nothing from `broker` or `execution`, so the
  market-data-only boundary is structural rather than a convention. Falsified
  by an import graph that reaches either.

## Test list

- success: a two-page fixture returns every symbol, in session order, with the
  adjustment and asof the config named.
- success: a decimal price such as `178.005` maps to exactly that `Decimal`,
  which a float path would not preserve.
- success: a news article maps to `Article` with the integer id stringified and
  the symbols preserved.
- failure: a bar request without an explicit asof raises, naming the parameter.
- failure: a client returning one unchanging page token raises
  `PaginationLimitError` after `max_pages`.
- failure: a requested symbol absent from every page raises
  `IncompleteCoverageError` naming the symbol, under required coverage.
- failure: a payload missing a required price field raises
  `UnusableRecordError` rather than substituting zero.
- failure: an exception raised while a marker secret is configured does not
  contain the marker.
- restart: two runs over one recorded fixture produce byte-identical records,
  under two hash seeds.
- restart: a revised article and its original both survive a round trip through
  UNIT-020's recorder as two observations.
- no-trade: a symbol with no news in the window yields no articles and no
  error, because silence is an ordinary outcome for a news feed.
- no-trade: an empty page with a null token ends the loop and returns nothing
  rather than raising.

## Verification

```bash
uv run pytest tests/research/test_alpaca_adapter.py tests/research/test_pagination.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes

- 2026-08-29, D-025: `Article` gains a summary field, so this adapter maps
  Alpaca's `summary` into it. That field is required on every article in the
  reference, so a payload without one is a contract violation rather than a
  normal case. Do not set `include_content` and do not use
  `exclude_contentless`: the first pulls HTML this project has not decided to
  accept, and the second selects the research sample on a property correlated
  with the outcome. UNIT-030 widens the record and this unit now depends on it.
