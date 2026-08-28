---
name: handoff
description: Create a concise, evidence-based development checkpoint for the next AlphaLedger session.
origin: AlphaLedger
disable-model-invocation: true
---

# Create a session handoff

Update `project-state/STATUS.md` in place. Preserve its headings and
keep the file concise enough to load every session.

1. Read the current status, decisions, `git status --short`, and the relevant
   diff. Do not read secrets or generated datasets.
2. Record only verified facts:
   - current phase and active gate;
   - what changed in this session;
   - tests or validations actually run and exact outcomes;
   - current paper account state only if obtained through the application and
     already safely summarized;
   - blockers and unresolved assumptions;
   - the next three bounded tasks in priority order; and
   - the files the next session should read first.
3. Add an entry to `project-state/DECISIONS.md` only for a real accepted
   decision with date, rationale, alternatives, and reversal condition. Do not
   turn experiments or suggestions into decisions.
4. Do not commit, push, place orders, or mark a gate passed without its named
   evidence artifact.

End by showing the status diff and a one-paragraph restart instruction.
