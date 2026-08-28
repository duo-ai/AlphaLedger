---
name: spec-clarify
description: Resolve open questions in a spec or plan by asking one at a time and writing each answer back immediately. Use after spec-analyze finds anything CRITICAL or HIGH.
origin: AlphaLedger
---

# Clarify

Turn open questions into decisions. This is the only step in the pipeline that
is a conversation, and it is deliberately narrow: at most five questions, one
at a time, each written back before the next is asked.

Run it on the spec after `spec-analyze`, and again on the plan if planning
raised new questions.

## Choosing the questions

Take the `[NEEDS CLARIFICATION]` markers and the CRITICAL and HIGH findings
from `analysis.md`. Rank by impact times uncertainty: how much of the work
changes depending on the answer, multiplied by how unsure you actually are.

Five is the ceiling, not a target. Two good questions beat five that pad.

Do not ask what you can decide. If a reasonable default exists and the choice
does not change scope, safety, or what the thing is for, decide it and record
it under Assumptions. The author's time is the scarce resource.

## Asking

One question per message. Offer two to four concrete options, say which you
recommend and why, and make each option answerable in a few words. A question
that requires an essay to answer is a question you have not thought through
enough to ask.

State what changes depending on the answer. "This decides whether the recorder
owns the ordering check or the adapter does" is useful. "Please confirm the
approach" is not.

## Writing back, immediately

After each answer, before asking the next:

1. Append to `## Clarifications` in the spec or plan, under a dated session
   heading, one line: the question, then the answer.
2. Edit the section the answer affects. Replace the ambiguous statement; do not
   leave it standing next to its own correction. An obsolete sentence beside a
   new one is worse than the original ambiguity, because now two readings are
   both textually supported.
3. Remove the `[NEEDS CLARIFICATION]` marker it resolved.

Writing back immediately is what makes this survive an interruption. A session
that dies after three answers leaves three resolved questions, not a lost
conversation.

## Finish by

Re-running `spec-analyze` and reporting what moved: findings resolved, findings
still open, and any new finding the answers introduced. Answers do introduce
findings; a decision that resolves one ambiguity often sharpens a conflict
elsewhere.

Then say plainly whether the artifact is fit to proceed. If questions remain
open and unanswerable right now, leave the markers in. `coord.py` refuses to
claim a unit carrying one, which is the correct outcome: the work is not ready,
and pretending otherwise moves the cost to whoever implements it.
