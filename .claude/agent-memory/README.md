# Agent memory

Committed, shared, per-agent memory. Each specialist writes its own directory
here and reads it back on its next invocation, so knowledge accumulates across
sessions and both developers see it.

This is the shared channel. Claude Code's auto memory lives outside the
repository at `~/.claude/projects/<project>/memory/` and is machine-local, so
anything written there reaches one person on one machine and no one else.

## Layout

```
.claude/agent-memory/<agent-name>/
    MEMORY.md      the index, one line per entry, loaded at agent start
    <topic>.md     the detail, loaded on demand
```

Only the first 200 lines or 25KB of `MEMORY.md` is injected. Keep it an index.
Put the substance in topic files.

## Convention, and the reason for it

Two people commit to this directory, and the documentation says nothing about
merging two versions of one `MEMORY.md`. So: one line per entry in the index,
newest last, and each entry's detail in its own file named for the topic. Two
appends to the end of a list merge cleanly. Two rewrites of a paragraph do not.

Write an entry when something would otherwise have to be rediscovered:

- a defect class that recurred, and the shape of the test that catches it;
- a project invariant that is easy to violate and expensive to notice;
- a decision's practical consequence, not the decision itself, which belongs in
  `project-state/DECISIONS.md`.

Do not write here what the repository already records. A summary of the design
spec is not memory, it is duplication that will drift.

## The boundary

Enabling memory grants an agent Read, Write, and Edit even where its `tools:`
list omits them, which is why D-019 amends D-004. Those tools exist for this
directory. A reviewer that edits application code, a spec, or a test has
exceeded its role no matter what the tool list permits, and its finding should
have been a report instead.
