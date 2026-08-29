---
name: mutation-testing-discipline
description: Independently re-run mutation probes against an implementer's self-reported defect-injection count rather than trusting the number in the handoff notes.
metadata:
  type: feedback
---

When a unit's handoff notes claim "N deliberate defects injected, M caught, K survived and were judged benign," treat that as a starting point, not a ceiling. On UNIT-023 the notes claimed twelve mutations with two documented survivors (an AC-1 coverage gap, since fixed, and a `hashlib` vs salted-builtin-`hash` swap judged behavior-preserving). Independently injecting four more targeted mutations found two additional survivors the notes never mention:

1. `age > horizon` → `age >= horizon` in the lookback filter: full suite still green. Correct call: not a finding, since no test pins the exact boundary and no numbered AC governs the lookback cutoff (it isn't a leakage control, both operators keep the article at-or-before `as_of`).
2. Anchor-relative cluster windowing → chained/transitive windowing (compare each article to the previous one instead of a fixed anchor): full suite still green, but `independent_source_count` changes materially on a constructed fixture (3 articles at ages 80h/40h/0h under a 48h window: anchor-relative gives 2, chained gives 1). This is a genuine test-coverage gap bearing on AC-2 (syndication collapse correctness), worth reporting as LOW/MEDIUM even though the *implemented* behavior is the better design choice (anchor-relative bounds every cluster's time span; chained does not, so a story republished every 40h under a 48h window would chain indefinitely and understate the source count without limit).

**Why:** the implementer's own count is exactly the kind of self-graded evidence AGENTS.md warns against ("claims that are stronger than the recorded evidence"). Two of twelve missed defects is a normal rate for careful work, not a sign of sloppiness, but a reviewer who only re-reads the code and doesn't independently mutate will never know the count was incomplete, the notes read as "the suite is now mutation-tight except one benign case" when it demonstrably was not.

**How to apply:** on every research-lane review, spend a few minutes constructing 3-5 targeted mutations of the load-bearing arithmetic/branching (denominator swaps, boundary operators `>` vs `>=`, exclusion branches, the specific windowing/clustering algorithm named in the docstring as a deliberate choice) and run the test file against each. Report survivors even if they don't change the verdict, a survivor on correct-but-undertested behavior is a LOW/MEDIUM coverage finding; a survivor that changes an assertion is a real bug. See [[unit-023-news-features]] for the worked example and [[d022-bounded-mandate]] for how to grade what you find.
