---
name: d022-bounded-mandate
description: How to grade a finding under D-022's "actionable + bears on a numbered AC" rule when the code is correct but a specific edge case is untested.
metadata:
  type: feedback
---

D-022 bounds a reviewer's mandate to findings that are (a) actionable inside
the unit's declared path globs and (b) bear on one of its numbered acceptance
criteria. A recurring judgment call: what to do with a finding where the
*implemented* behavior is correct and is the better of two plausible designs,
but no test would catch a regression to the worse design.

**Rule of thumb, confirmed by the advisor on UNIT-023's clustering-windowing
gap:** this is a real, reportable finding (it satisfies both D-022 conditions,  it's inside the test file's glob, and it bears on AC-2's "one wire story
counts once" claim) but it does not block. Grade it LOW/MEDIUM, state plainly
that the current behavior is not a bug and briefly say why the implemented
choice is the sound one, and give the drop-in test as the correction. Do not
inflate it to conditional/block just because you found something, D-022's
whole point (see also the STATUS.md quote "a reviewer that never clears
anything is not a stricter reviewer, it is a gate that does not open") is that
a unit whose ACs demonstrably hold clears, and a missing regression guard on
correct behavior is forward-looking risk, not a present defect.

Contrast with what *would* block: a mutation that changes an assertion's
outcome (wrong arithmetic, a leak that isn't checked, an exclusion branch that
doesn't fire), those are present defects regardless of AC wording, because
they mean the shipped code doesn't do what the AC claims right now.

See [[unit-023-news-features]] for the worked example and
[[mutation-testing-discipline]] for how the finding was surfaced.
