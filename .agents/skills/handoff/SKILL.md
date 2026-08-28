---
name: handoff
description: Use only when the user explicitly invokes $handoff to create an evidence-based AlphaLedger checkpoint for the next development session.
origin: AlphaLedger
---

# Create a session handoff

Update `project-state/STATUS.md` in place. Preserve its headings and keep it
concise enough for every future coding-agent session.

1. Read the current status, decisions, `git status --short`, and the relevant
   diff. Do not read secrets or generated datasets.
2. Record only verified facts:
   - current phase and active gate;
   - changes from this session;
   - validations actually run and exact outcomes;
   - paper-account state only if obtained through the application and already
     safely summarized;
   - blockers and unresolved assumptions;
   - the next three bounded tasks in priority order; and
   - files the next session should read first.
3. Add an entry to `project-state/DECISIONS.md` only for an accepted decision
   with date, rationale, alternatives, and reversal condition. Experiments and
   suggestions are not decisions.
4. Do not commit, push, place orders, or mark a gate passed without its named
   evidence artifact.

End by showing the status diff and one concise restart instruction.
