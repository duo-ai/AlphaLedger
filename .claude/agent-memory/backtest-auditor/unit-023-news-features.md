---
name: unit-023-news-features
description: Round-one review facts for UNIT-023 (src/alphaledger/evidence/news.py, labeler.py), arithmetic verified by hand, determinism verified, one coverage gap found and cleared anyway.
metadata:
  type: project
---

Reviewed 2026-08-29, round one, verdict clear. `alphaledger.evidence.news.build` and
`alphaledger.evidence.labeler`.

**Confirmed correct by hand:** the eight features' arithmetic against the fixture
in `tests/research/test_news.py` (`FRESH`/`DAY_OLD`, half_life=24h making the
day-old article's decay exactly 0.5). `surprise_weighted`'s different
denominator (`known_total`, excluding `surprise=unknown` labels) is correct and
bounded; mutating it to use the shared `total` instead is caught by
`test_one_unknown_surprise_among_several_leaves_the_feature_on_the_rest`.

**Confirmed correct: the `event_time` exemption (D-014) is properly scoped.**
`event_time` is carried on `Article.timestamps` (an `ObservationTimestamps`)
but is never read anywhere in `news.py`, not in the leak check, not in decay,
not in any ratio. It literally cannot leak because nothing consumes it. Only
`first_seen_time` gates the leak check, on both the article and the label
independently (a label carries its own `first_seen_time`/`source_time` and is
checked against `as_of` and against the article's recorded values, this is
what catches a label produced from a later observation of the same article,
which the article's own timestamp can't).

**Confirmed correct: determinism.** `_clusters` groups by SHA-256 hex digest
(not the salted builtin `hash`), sorts groups by digest string, and sorts
representatives by `(first_seen_time, article_id)`, a total order since
`article_id` is unique within `held` (duplicate ids must be byte-identical or
raise `AmbiguousArticleError`). Verified with `PYTHONHASHSEED=0` vs `54321`
subprocess comparison (`test_two_processes_produce_byte_identical_output`),
which actually passed when I re-ran it, not just per the handoff notes.

**The one real finding: clustering windowing has no regression test pinning
its specific algorithm.** `_clusters` (news.py:499-541) uses anchor-relative
windowing: a cluster's anchor is fixed at the earliest member, and every
subsequent article is compared against that fixed anchor's timestamp, not the
previous member's. This bounds every cluster to span at most
`cluster_window_hours`. Mutating it to chained/transitive windowing (compare
each article to the previous one) passes the entire existing test suite
unchanged, but changes `independent_source_count` from 2 to 1 on a
constructed 3-article fixture (same canonical headline at ages 80h/40h/0h,
`cluster_window_hours=48.0`). Anchor-relative is the better design (bounded
span; chained would let a story republished every 40h chain indefinitely and
understate the source count without limit), so this is a missing regression
guard, not a latent bug, graded LOW/MEDIUM, non-blocking. Recommended test
(drop-in, values already computed): three articles sharing a canonical
headline at ages 80h/40h/0h under `NewsFeatureConfig(cluster_window_hours=48.0,
lookback_hours=200.0)` should assert `independent_source_count == 2.0` and
`SYNDICATION_COLLAPSED in quality_flags`.

**Handoff notes claim two mutation survivors (an AC-1 gap, fixed, and the
hashlib-vs-`hash` swap, judged benign).** Independent re-probing found two
more the notes don't mention, see [[mutation-testing-discipline]] for the
general lesson and the exact mutations run.
