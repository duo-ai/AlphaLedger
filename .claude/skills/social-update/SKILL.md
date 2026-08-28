---
name: social-update
description: Draft today's public progress update for AlphaLedger from real repository evidence, for human review before posting.
origin: AlphaLedger
disable-model-invocation: true
---

# Draft the daily social update

Produce a reviewable draft. Never post, never authenticate to a social
platform, and never treat this skill as permission to publish.

## 1. Gather evidence

Read only what actually happened today:

```bash
git log --oneline --since=midnight
python3 scripts/coord.py list
```

Then read `project-state/STATUS.md`, the `gates:` block of the run manifest,
and any unit that changed state today. If the evidence ledger exists, read the
count of decisions and no-trades, not the P&L.

If nothing changed today, say so in the draft and stop. A quiet day is a
legitimate update. Do not manufacture progress.

## 2. Hard constraints

These are not style preferences. A draft that breaks one of them is discarded.

- Paper trading only, stated explicitly in any post that mentions trading.
- No profit, loss, return, equity, or account-balance figure. Not even a
  positive one, and not "up X%" in any form.
- No account identifier, order id, API key name, endpoint, or screenshot that
  contains any of these.
- No claim that the system is profitable, validated, live-ready, or will make
  money. Gates that have not passed are described as not passed.
- No forward-looking statement about results.
- Describe what was built and what was learned. Engineering progress, research
  discipline, and honest negative results are the material.
- A `no_trade` decision is a good post. It is the system working.

## 3. Write the draft

Write to `social/YYYY-MM-DD.md` using today's date. Include:

- one short post, roughly 280 characters;
- one longer post, roughly 3 short paragraphs;
- the exact evidence each claim rests on, as a bullet list at the bottom, so a
  reviewer can check every sentence against an artifact.

Use plain language. No em dashes, no emoji, no hashtag stuffing, and no
phrasing that reads as generated. Match the tone of the repository prose.

## 4. Hand off

Print the draft path and stop. Tell the user the draft is ready for review and
that posting is theirs to do.
