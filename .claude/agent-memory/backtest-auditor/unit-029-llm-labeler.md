---
name: unit-029-llm-labeler
description: Round-one review facts for UNIT-029 (src/alphaledger/evidence/llm_labeler.py). Conditional verdict, tie-timestamp crash in label_batch found by direct probe, plus a mutation that stays undetected.
metadata:
  type: project
---

Reviewed 2026-09-01, round one, verdict conditional. `alphaledger.evidence.llm_labeler`,
the LLM-backed `NewsLabeler` adapter, cache, and `label_batch`.

**The one real finding: `label_batch` crashes the whole ticker's batch when two
articles for that ticker share an identical `first_seen_time`.** Confirmed by
direct probe, not by mutation: two `Article` objects with different
`article_id` and the same `first_seen_time` handed to `label_batch` raise an
uncaught `LabelerContractError` from `_check_panel`'s strict inequality
(`item.timestamps.first_seen_time >= subject.timestamps.first_seen_time`).
`label_batch`'s own `try/except` only catches `UnusableLabelError`, an
unrelated exception hierarchy, so nothing in the batch entry point stops this
from propagating. This directly contradicts the module's own docstring
("breaking ties by `article_id`, so each article's prior context is a function
of the data rather than of the order a feed returned") and the unit's stated
purpose (a "tolerant batch entry point ... rather than raising out of an
entire ticker's run"). Realistic trigger: same-second wire-story publication,
plausible whenever `first_seen_time` has coarse (e.g. minute-level) buffer
granularity. No test in the suite uses tied timestamps inside `label_batch`
(only `label()` called directly is tested at that boundary), so nothing caught
it. Correction: filter the context slice built in `label_batch` to items whose
`first_seen_time` is strictly less than the current item's, not by catching
`LabelerContractError` there. Catching it would collapse "the panel is
mis-assembled" into "this one article is excluded," which the module
explicitly refuses to do elsewhere (a foreign-ticker article aborts the whole
batch, tested by `test_the_batch_refuses_a_panel_holding_a_foreign_article`).

**A mutation that stays fully green, worth reusing whenever `label_batch`-shaped
code is reviewed again.** Moving `seen.append(item)` inside the `try` block (so
only successfully labeled articles contribute to later prior context) leaves
all 38 tests passing. The current code is correct, appending unconditionally
so a later article's context reflects what was published regardless of
whether the model succeeded on the earlier one, which matters because a
transient `ModelClientError` must not change a later article's cache key on
replay. But nothing pins this property, so a naive fix to the tie-timestamp
bug above (e.g. wrapping more into the `try`) could silently reintroduce a
gap. Recommended regression test: a batch where the middle article is excluded
via a `ModelClientError`, asserting the next article's sent
`prior_story_context` still contains the excluded one.

**Confirmed correct by direct probe (not just reading), the low-risk items:**
cache_key/model_payload cannot structurally diverge because `cache_key` builds
its hash input by spreading `model_payload(...)`'s own return value, so both
call sites in `label()` are guaranteed identical given identical arguments;
this is a stronger guarantee than a test comparing two independently-written
constructions. Point-in-time fields (`source_time`, `first_seen_time`,
`labeler_version`) come from `subject.timestamps`/adapter config
unconditionally in both the live-label path and the cache round trip; no
reply-supplied value can reach them anywhere, verified by reading every
assignment site, not just the tested one.

**LOW, documentation-only:** `_context_entry` sends four fields
(`article_id`, `source_time`, `source_domain`, `headline`) but the Contract
prose (the same paragraph amended this round for the summary fix) says
`prior_story_context` holds only `source_time`/`source_domain`/`headline`,
three. Not a functional bug (the key hashes the actual payload, so key and
payload can't drift apart), and `article_id` isn't sensitive since the
requesting caller already knows it. Separately, the Contract and AC-7 both
say "nine Prompt-B-schema fields" while listing eleven and matching the code's
eleven-item `_SCHEMA_FIELDS` tuple exactly; the list and the code are right,
only the word "nine" is wrong. Both are pre-existing text this round's diff
didn't introduce (only the summary line changed), so out of scope for a
severity grade, but worth a one-line note back to the implementer.

**Out of scope, recorded so a future unit does not assume this round's fix
covers it:** `alphaledger.evidence.labeler.labels_by_article`, merged by
UNIT-023, sorts and builds prior context the identical way and has no `try`
at all, so an `LlmNewsLabeler` handed to it hits the same tie crash with no
tolerance whatsoever. Outside this unit's declared globs (`labeler.py` isn't
in `paths`), not raised as a severity-bearing finding, but whichever unit
wires this adapter into `labels_by_article` (deferred per this unit's own
Scope, Out) will need the same fix or will inherit the crash believing
`label_batch`'s correction already covers it.

**Measurability, per D-021: no AC found structurally untestable.** Every one
of AC-1 through AC-16's falsification clauses names an observation the test
suite actually makes; ran the full suite (`uv run pytest
tests/research/test_llm_labeler.py -q`, 38 passed) and spot-checked several
by temporary mutation (see [[mutation-testing-discipline]] for the general
method). AC-16's own test only exercises put-put on one instance; a
put-reopen-put-same-key sequence isn't directly tested but is structurally
safe because the constructor rebuilds the whole index from the store, so this
belongs under "what remains unverified" rather than as a finding.

**The implementer's own Contract amendment (summary field: empty string to
`subject.summary`) is a legitimate correction, same pattern as UNIT-030's.**
Cites D-025 and D-026, both dated before this unit's work, and makes the
criterion more accurate rather than more convenient. See
[[unit-030-article-summary]] for the two discriminators used to judge this.

**Round two, 2026-09-01, verdict clear.** Commit `a9e473a` fixed the tie
finding by filtering `label_batch`'s context to strictly-earlier articles
(`prior.timestamps.first_seen_time < item.timestamps.first_seen_time`), not by
widening the `except`, as warned against. Reverting the filter to the old
`seen[-max_prior_context:]` line sends both new tie tests red on the real
`_check_panel` exception, not on an assertion mismatch, confirming they pin
the mechanism rather than a symptom. The `seen.append(item)` landmine from
round one is now covered by `test_an_excluded_article_still_counts_as_prior_context`;
moving the append inside the `try` (right after the successful assignment)
sends it red. The slice bound moved from `seen[-max_prior_context:]` to
`earlier[-max_prior_context:]`, i.e. the tail of the *filtered* list rather
than of `seen` itself; since `earlier` is a list-comprehension over `seen`
that preserves order, the tail of the filtered list is still "the last N
strictly-earlier articles," so the N-article bound still means the same thing
`labels_by_article` means by it.

**A test coupling worth knowing about, not a defect.**
`test_a_tied_article_is_withheld_while_a_strictly_earlier_one_is_shown` also
goes red when the landmine mutation is applied, not just the test built for
it. Reason: its "earlier" article (`art-0`, headline "Acme schedules an
investor day") is built with a custom headline but `reply()`'s default
`evidence_spans` is still `["raised its full year guidance"]`, a string that
appears in neither `art-0`'s custom headline nor the shared default summary.
So `art-0`'s own `label()` call fails `_check_spans` and lands in `excluded`,
and the test only passes because `art-0` still counts as prior context for
`art-A`/`art-B` despite being excluded, i.e. it accidentally also exercises
the landmine property. Confirmed by an isolated `label_batch` call: `excluded
== {'art-0': "evidence span 'raised its full year guidance' does not appear
verbatim..."}`. Not a bug: the test's actual assertions only check what was
sent to the client as `prior_story_context`, which is true regardless of
whether `art-0`'s own labeling succeeded, so it still tests what its docstring
claims. Worth knowing before assuming "only the pinned test should go red on
this mutation" as an isolation property; it doesn't hold here, harmlessly.

**Mutation-test replacement for AC-7 verified for real.** The old
`not hasattr(label, "trade")` assertion was replaced with an iteration over
`NewsLabel.__dataclass_fields__` checking no field's stringified value
contains the injected reply content. Injected the exact mutation the
implementer claims to have run (`limitations=(str(held),)`, parking the whole
reply mapping in `limitations`) and the new test caught it; the old
`hasattr`-based version could not have, since `NewsLabel` is a slotted frozen
dataclass.

**`_check_spans` docstring claim about `evidence_spans` never being read
downstream, verified independently.** `evidence/news.py` reads
`article_id`, `ticker`, `entity_match`, `category`, `direction`, `novelty`,
`relevance`, `surprise`, `ambiguity` off a label but never `evidence_spans`;
the only non-test, non-`llm_labeler.py` reference to the field anywhere in
`src/` is its declaration in `domain/contracts.py`.

See [[mutation-testing-discipline]] for the general probing method.
