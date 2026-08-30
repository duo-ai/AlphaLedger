---
name: unit-030-article-summary
description: Round-one review facts for UNIT-030 (Article.summary field). Clear verdict, legitimate implementer AC amendment, dynamic AC-5 guard verified by mutation.
metadata:
  type: project
---

Reviewed 2026-08-30, round one, verdict clear. `alphaledger.evidence.news.Article`
gains a required `summary: str` field.

**Confirmed independently, not just trusted from the handoff:** `uv run pytest
tests/research/test_news.py` at 71 passing (baseline 62, so 9 additions),
full suite 599 passing, ruff and mypy clean. Zero deletion lines in the two
code/test files (`git diff develop...HEAD -- tests/research/test_news.py
src/alphaledger/evidence/news.py | grep -c '^-[^-]'` returns 0), which is a
stronger AC-4 proof than the 71-vs-62 count alone: nothing was loosened,
only added.

**The AC-2/AC-2a split (implementer amended the AC to match the
implementation) is a legitimate clarification, not the UNIT-010 self-serving
pattern.** Two discriminators that generalize beyond this unit, worth
checking whenever an implementer edits its own acceptance criterion:

1. Does it cite a decision recorded independently, before the unit's own
   work started? Here, D-025 (2026-08-29, the day before) already established
   that filtering articles on how little their text says is a selection
   effect, not a cleaning step. The amendment applies an existing, external
   constraint rather than inventing a new rationale to fit what got built.
2. Does the amendment make the criterion more falsifiable, not less? The
   original AC-2 ("feeds each rejected shape the headline rejects") named no
   observation that would falsify it against D-025; the split adds AC-2a,
   which names an exact observation (a punctuation-only summary must be
   accepted) that would fail if the implementer had simply copied the
   headline check.

Contrast with UNIT-010's redirect AC: that one was physically unsatisfiable
(the body is already sent by the time a redirect response exists) and the
same author who wrote the unsatisfiable AC also wrote a test list that
reproduced its false premise, no independent source resolved the
contradiction. Here an independent, dated decision resolves it, and the
resulting test list is stricter than before, not weaker.

**Verified AC-5 (nothing else changed) with an actual dynamic mutation, not
just a grep.** Grepping confirms `summary` is read nowhere in `news.py`
except its own field/validation, but a reviewer should still run the
regression: mutate the clustering key in `_clusters` to include
`article.summary` (`_canonical_hash(article.headline) + article.summary`)
and confirm the test suite catches it. It does, both the new
`test_a_summary_equal_to_the_headline_changes_no_feature_outcome` and a
pre-existing UNIT-023 test (`test_punctuation_and_case_do_not_split_one_wire_story_in_two`)
fail. This is the general pattern worth reusing when a unit widens a record
and claims "nothing else changed": build two fixtures that are identical
except in the new field (here: `restated` with summary==headline vs
`distinct` with a different summary per article), pin the collapsed value
first (`independent_source_count == 1.0` for `restated`, checked before the
equality assertion), then assert full feature-dict and quality-flag equality
between the two. Pinning the value first means the equality check can't pass
by both sides being equally wrong.

**Measurability note, not a finding:** the test list's `restart` line
("survives whatever path UNIT-020 stores it through") names an observation
that is not physically available. `Article` appears nowhere under
`src/alphaledger/data/`, UNIT-020's Recorder does not know this type, so
there is no storage path yet to round-trip through. The implemented test
(`test_the_summary_survives_a_field_by_field_reconstruction`) is a
construction-echo, `Article(**original's fields) == original`, which holds
for any dataclass regardless of the summary field's correctness. This is
inherited from UNIT-023's own "restart" tests (which are subprocess
determinism checks, not storage round-trips either), so it's not a new gap
this unit introduced; note it in future news-family reviews rather than
re-discovering it, and don't grade it since the numbered ACs (which is what
D-022 bounds severity to) are all measurable and satisfied. Only the
test-list prose overreaches.

See [[mutation-testing-discipline]] for the general probing method and
[[d022-bounded-mandate]] for how a coverage gap on correct behavior is
graded.
