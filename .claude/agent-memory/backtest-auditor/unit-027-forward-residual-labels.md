---
name: unit-027-forward-residual-labels
description: Round-one review facts for UNIT-027 (src/alphaledger/evidence/labels.py), the peer-gap outcome_time leak and the delisting-raises-instead-of-None defect, both confirmed by constructed counterexamples.
metadata:
  type: project
---

Reviewed 2026-08-29, round one, verdict block. `alphaledger.evidence.labels.build`
and `with_uniqueness`.

**Finding 1, the real one: `_outcome_time` does not cover every bar that fed
the residual, specifically a peer's predecessor bar reached through a gap.**
`_residual_sum` computes `peer_returns = [_returns(peer) for peer in peers]`
over each peer's whole series, not restricted to `window`. If a peer is
missing a bar for one session inside `window`, `_returns` silently produces a
multi-session return for the next session that peer does have, using
whatever bar precedes the gap as "previous," which can sit outside `window`
entirely. `_outcome_time` only scans bars inside `window`, so that
predecessor bar's `first_seen_time` is invisible to it. Constructed and ran:
a peer missing two consecutive in-window sessions, its predecessor bar's
`first_seen_time` set two years late (a data revision), still produced a
label with `outcome_time` unchanged and `quality_flags=()`, no flag at all.
This is AC-3's own stated falsification ("delay one bar's `first_seen_time`
past the others and observe `outcome_time` unchanged"), run against a peer
bar instead of an own bar. The existing test
(`test_outcome_time_is_the_latest_first_seen_not_the_exit_session`) only
delays the *own* exit bar, the one case the contiguous-slice structure of
`own`'s session list already makes safe by construction; it never exercises
a peer.

Two economically distinct halves, graded differently:
- The temporal half (a consumed bar excluded from `outcome_time`) is
  unit-local to `labels.py`, has no analogue in UNIT-022 (nothing there feeds
  a purge), and is fixable entirely inside this file: have `_residual_sum`
  report which `(symbol, session)` bars it actually consumed, peer
  predecessor included, and max over that set instead of over `window`.
  HIGH, blocks.
- The economic half (a stale multi-session peer return silently entering the
  median with no flag) is inherited from UNIT-022's `_return_by_session` /
  `_demeaned`, which has the identical mechanic and is pinned to match by
  `test_the_demeaning_agrees_with_the_price_feature_family`. A unilateral fix
  here would break that pinned agreement. Route to the shared refactor unit
  both intakes already name for `NewsFeatureBlock`-style duplication. MEDIUM,
  does not block on its own.

**Finding 2: a symbol delisted immediately after the decision raises
`InsufficientHistoryError` instead of returning `None`, contradicting AC-4's
own text.** `entry_index = len(decided) - 1 + entry_offset_sessions` is
computed against `own`'s own session list only. If this specific symbol's
own bars end right after the decision, while every peer and the rest of the
panel keeps trading for weeks, `entry_index >= len(sessions)` fires and
raises with the message "The panel was built wrong; this is not a missing
outcome." Constructed and ran: peers with 20 sessions, `TARGET` with only 6,
decision on `TARGET`'s last session. Raised. AC-4 says "a label whose
horizon does not complete, because the panel ends or the symbol stops
trading, returns `None`," with no carve-out for stopping trading
*immediately* versus mid-horizon, and the caller cannot precompute this
symbol-specific case from the panel's overall bounds the way it could a
uniform, known panel end date. The test list's own line
("failure: a panel ending before the entry session raises
`InsufficientHistoryError` naming the symbol and the session") contradicts
AC-4's prose, and the implementation followed the test list. Same author
wrote the AC and the test list, so the contradiction survived TDD; see
[[mutation-testing-discipline]] and D-021 in `project-state/DECISIONS.md` for
the general shape of this failure mode. HIGH, blocks.

**Measurability pass surfaced why both survived.** AC-4's own stated
falsification ("truncate the panel and observe a label whose value is zero")
cannot distinguish `None` from `raise`, both are non-zero, so the AC's
prose is stronger than its own falsification test and nothing forced the
implementation toward the stronger reading. AC-10's stated falsification
("construct a fold from the emitted labels and observe a label placed in a
window its outcome instant should have purged it from") is never
implemented; `test_as_labelled_round_trips_into_the_split_contract` checks
only field equality, no fold is ever built with `alphaledger.forecast.splits`.
That unimplemented test is exactly the one that would have caught Finding 1
end to end, which is the concrete correction to point at rather than a bare
coverage complaint.

**Mutation probes, done independently of the handoff's claimed twelve.**
`statistics.median(cross_section)` swapped for `statistics.mean` passes the
entire suite unchanged, because the test fixture's `PEERS = ("PEER1",
"PEER2")` is always exactly two peers, and the median of two numbers is their
mean. Real coverage gap on AC-2's explicit "median" wording, LOW/MEDIUM, same
disposition as [[unit-023-news-features]]'s clustering-windowing gap: correct
implementation, no regression guard, worth a three-or-more-peer fixture.
`abs(value) > config.implausible_return` swapped for `>=` also survives, LOW,
boundary-only. A genuine duplicate `label_id` passed twice into
`with_uniqueness` silently produces uniqueness 0.5/0.5 for both copies rather
than being refused, unlike this same module's own `AmbiguousBarError`
pattern for a conflicting bar; no test constructs this (the existing
"two labels overlap completely" test deliberately assigns different
`label_id`s). MEDIUM, worth a decisive test either way (refuse or document
as accepted caller obligation).

See [[mutation-testing-discipline]] for the general lesson and
[[d022-bounded-mandate]] for grading a correct-but-undertested finding versus
a present defect; both Findings 1 (temporal half) and 2 here are present
defects (an assertion's outcome changes / an AC is contradicted by
demonstrated input), not coverage gaps on correct behavior, which is why they
block rather than being graded LOW/MEDIUM like the mean/median and duplicate
label id findings.
