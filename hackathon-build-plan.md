# AlphaLedger — solo hackathon build plan

Event: Alpaca AI Trading Agents Hackathon, Options Alpha Agents track  
Kickoff: Friday, 28 Aug 2026, 15:00 UTC / 11:00 ET  
Deadline: Friday, 4 Sep 2026, 15:00 UTC / 11:00 ET  
Builder: solo  
Canonical architecture: `options-alpha-agent-design.md`

During this event, ET is daylight time (UTC−4). Use the exchange calendar and
broker clock in code rather than hard-coding conversions.

## 1. Planning principle

The prior schedule delayed paper execution until Day 4 and explicitly treated
it as cuttable. That is incompatible with a competition whose official
announcement emphasizes paper-account P&L and an autonomous agent.

This schedule builds one complete, deliberately simple vertical slice on the
first open-market afternoon:

```text
data -> one frozen signal -> one defined-risk spread -> risk approval
     -> paper order -> reconciliation -> monitoring -> exit -> ledger
```

The weekend is then used to replace the placeholder signal with a
chronologically validated price/news forecast. A pretty interface, more
strategies, external search, and multi-agent features come only after the
full lifecycle is reliable.

## 2. Non-negotiable deliverable and success gates

### Must ship

- autonomous paper-only scanner over a frozen liquid universe;
- point-in-time price/volume and Alpaca news evidence;
- locked walk-forward forecast with at least two baselines;
- one validated defined-risk options expression (debit vertical);
- entry, idempotency, fill reconciliation, monitoring, and automated exit;
- portfolio risk limits and a kill switch;
- append-only evidence/trade ledger; and
- a demo/dashboard that shows P&L, risk, evidence, `no_trade`, and shadow books.

### Gates

| Gate | Deadline | Pass condition | If it fails |
|---|---|---|---|
| G0 Rules/account/data | Aug 28, 16:00 UTC | Correct competition account, paper endpoint, balance, permissions, feed mode, submission rules recorded | Stop implementation assumptions and resolve; do not trade |
| G1 Order round trip | Aug 28, before market close | Submit/cancel/close/reconcile a tiny MLeg paper order through tested adapter | Switch from MCP wrapper to direct Trading API adapter |
| G2 Full dry lifecycle | Aug 28 end of day | Restart-safe state machine and ledger from candidate to flat | Weekend priority becomes lifecycle; no UI work |
| G3 Frozen alpha v1 | Aug 30 end of day | Chronological test, baselines, costs, trial log, signed config hash | Use validated price-volume fallback or no live alpha |
| G4 Autonomous session | Aug 31 market close | Agent ran all day without manual order decisions; every state reconciled | Reduce universe/cadence; fix operations only |
| G5 Submission freeze | Sep 2 end of day | No model/threshold/strategy changes; demo and write-up reproducible | Cut stretch work and freeze immediately |
| G6 Flat and submitted | Sep 4 before 15:00 UTC | All positions/orders reconciled flat; final artifacts submitted | Wind-down takes precedence over polish |

## 3. Day 0 — Thursday, Aug 27

Do only administrative, research, and generic integration work permitted by
the event rules. If pre-kickoff project code is prohibited, keep the submission
repository empty until kickoff.

### Required checks

- Start the selected coding harness from the repository root and inspect
  `/hooks`. Run `/bootstrap` in Claude Code or `$bootstrap` in Codex. Keep each
  committed Alpaca MCP server market-data-only; the application adapter owns
  account and order operations.
- Read the event page, track page, official announcement, submission form, and
  any rules released to participants. Record judging weights and all required
  artifacts verbatim.
- Provision or identify the dedicated competition paper account and verify
  whether it must start at exactly $100,000. Do not reset it after the live
  competition starts unless organizers explicitly permit it.
- Verify paper options level, multi-leg support, allowed symbols, and whether
  open mark-to-market or realized P&L determines ranking.
- Determine actual market-data entitlement: OPRA or Basic indicative options;
  IEX or SIP equities. Store the feed mode in the run configuration.
- Decide the tested integration path:
  - preferred: hosted competition paper MCP if organizers provision it;
  - otherwise: pin Alpaca MCP V2 to a known version;
  - fallback: a thin direct Trading API/SDK adapter for MLeg orders.
- Inspect the current `place_option_order` schema and test the documented
  `legs` array shape in a disposable environment. The MCP repository has had a
  reported multi-leg serialization issue; do not rely on untested docstrings.
- Create a secret-handling checklist. Keys live in environment/secret storage,
  never chat, logs, screenshots, notebooks, commits, or the evidence ledger.
- Confirm the demo-video limit, public-repository/license requirements, and
  submission cutoff. Create placeholder headings for the one-page write-up.

### Output

Complete the checked-in `run_manifest.example.yaml` without secrets. It already
contains the account mode, feed mode, MCP/API version, universe rule, scan
times, risk defaults, strategy allowlist, source URL, and gate placeholders.
Copy it to the runtime configuration only after the facts are verified. G0
remains unpassed until every required field matches the actual competition
environment and the frozen copy has a recorded hash.

## 4. Day 1 — Friday, Aug 28: execution-first vertical slice

The event begins at 11:00 ET while the market is open. Use the remaining
session to remove execution uncertainty.

### 15:00–16:00 UTC — lock rules and environment

- Complete G0.
- Verify market clock, account ID, equity, buying power, options permissions,
  positions, and working orders.
- Assert the base URL is the paper endpoint. Make live mode impossible in code,
  not merely discouraged in a prompt.
- Record version hashes and start the raw-data/ledger recorder.

### 16:00–18:00 UTC — order and state-machine smoke test

- Pull one liquid underlying and a 7–21 DTE chain.
- Build one valid one-contract debit spread from deterministic strike rules.
- Calculate debit, width, max loss/profit, and breakeven; test invariants.
- Risk-approve a tiny test within the frozen sandbox limit.
- Submit an MLeg DAY limit with an idempotent client order ID, query it by
  client ID, cancel or fill, reconcile activity and positions, then close and
  prove the account is flat.
- If MCP MLeg placement fails, switch immediately to the direct adapter. Do not
  spend the weekend debugging a presentation-layer wrapper.

### 18:00 UTC to market close — thin autonomous loop

Implement a placeholder, non-claimed signal solely to exercise the flow; it
must remain disabled for competition P&L unless it already passed a legitimate
historical test. Wire:

- static/frozen small universe;
- scheduled scan and one candidate result;
- `no_trade` path;
- deterministic debit-spread builder;
- risk approval token bound to payload hash;
- bounded limit-price ladder;
- order/activity/position reconciliation;
- one exit rule and emergency flatten;
- append-only decision and trade records; and
- crash/restart recovery from broker truth.

### Evening tests

- Paper/live endpoint assertion.
- Duplicate-run/idempotency test.
- Unknown submit result followed by lookup, never blind retry.
- Partial/working/cancel/reject transitions.
- Position-without-local-state recovery.
- Max-loss and spread-leg invariants.
- Daily-loss/kill-switch tests using mocked snapshots.

### Day-1 exit criterion

G1 and G2 pass. The system can safely do nothing, place one approved paper
spread, observe it, exit it, and recover after a restart. No dashboard polish.

## 5. Day 2 — Saturday, Aug 29: point-in-time research dataset

The market is closed; build the evidence layer without execution pressure.

### Morning — data and universe

- Build the lagged, frozen universe generator, capped at 20–30 names.
- Pull/cache historical stock bars, SPY, static sector ETFs, and Alpaca news.
- Normalize timestamps and save `source_time`, `first_seen_time`, `feed`, and
  `as_of`.
- Where historical delivery time or pre-revision article text is unavailable,
  apply the documented conservative availability lag, prefer immutable fields,
  and exclude unreconstructible inputs rather than treating retrieval time as
  event time.
- Create forward one- and three-session residual labels with purging rules.
- Add explicit sanity checks: duplicates, missing sessions, split/corporate
  actions, extreme values, stale records, and impossible future timestamps.

### Afternoon — structured news and price features

- Implement the fixed-schema news-labeling prompt from
  `orchestrator-system-prompt.md`.
- Batch labels; validate JSON; cache by article/content hash and prompt/model
  version.
- Deterministically cluster duplicates and syndications.
- Build residual-return, event-CAR, abnormal-volume, gap, and range/ATR
  features.
- The labeler never receives future returns or post-article market summaries.

### Evening — first baselines

- Generate price-only, news-only, and combined datasets.
- Run a shuffled-label/random-ranking negative control.
- Inspect feature distributions and timestamp leakage before fitting anything.

### Day-2 exit criterion

One command reconstructs a point-in-time feature table and forward labels from
raw cached data. Spot checks for several articles can be explained from input
to label to subsequent outcome.

## 6. Day 3 — Sunday, Aug 30: model, costs, and freeze candidate

### Morning — simple forecast

- Fit one regularized pooled directional model and one magnitude model.
- Use chronological expanding folds with a purge at least as long as the
  forecast horizon.
- Calibrate probabilities on a later slice.
- Do not add symbol-specific memorization or a large hyperparameter search.

### Afternoon — evaluation and option expression

- Run the locked test for random, price-only, news-only, and combined models.
- Report Brier/calibration, rank IC, sign precision, residual-return deciles,
  cost-adjusted P&L, max drawdown, turnover, and concentration.
- Model conservative debit-spread entry/exit costs. Never headline midpoint
  fills.
- Build the real-chain selector for only bullish and bearish debit verticals.
- Add quote freshness/spread/size gates and exact payoff/stress reports.
- If a pre-expiry repricer is not validated, label its output as stress, not EV
  or POP.

### Evening — go/no-go and freeze

Freeze alpha v1 only if:

- chronological results exceed the random baseline;
- the combined model improves on at least one single-family baseline without
  unacceptable deterioration elsewhere;
- performance is not one symbol, sector, event, or short time slice;
- conservative costs do not erase the result;
- threshold sensitivity is not a knife edge; and
- the trial registry includes every attempted variant.

Create immutable `model_version`, `feature_version`, `risk_config_hash`, and
`prompt_version`. After G3, only operational bug fixes are allowed unless the
system is disarmed and the change is prominently disclosed.

### Fallback if G3 fails

Use a separately tested price-volume model only if it already meets the same
gate. Otherwise keep live entry disabled, continue shadow forecasts, and use
Monday to fix data/leakage—not to lower the statistical bar.

## 7. Day 4 — Monday, Aug 31: first full autonomous market session

### Before open

- Deploy with one-process ownership or a reliable lock.
- Reconcile account/orders/positions from broker truth.
- Verify configuration hashes, feed mode, market calendar/clock, and data
  freshness.
- Arm once for paper trading with the frozen risk policy.

### During session

- Run the declared cadence; no manual ticker selection.
- Begin at half risk: maximum 0.375% equity loss per new trade and no more than
  two concurrent positions until the first complete round trip succeeds.
- Watch rejected, working, partial, and filled orders; measure fill latency and
  price ladder behavior.
- Check dashboard evidence against ledger records.
- Never modify a forecast, threshold, quantity, or order because the operator
  “likes” a candidate.

### After close

- Reconcile and attribute every P&L change.
- Compare broker P&L with conservative fill-adjusted P&L.
- Review only operational defects and data incidents.
- Promote to full frozen risk on Tuesday only if G4 passes.

## 8. Day 5 — Tuesday, Sep 1: reliability and counterfactuals

- Run the autonomous session with the same alpha/config.
- Fix only clearly logged implementation defects; version every change.
- Add price-only, news-only, and random/shuffled shadow curves to the dashboard.
- Add evidence cards for `no_trade` decisions, not just winners.
- Exercise controlled fault tests off-market: stale data, service timeout,
  duplicate event, unknown order result, kill switch, and restart recovery.
- If OPRA is available and the prebuilt options feature test passes, display
  its shadow contribution. Do not enable it live merely because it is
  interesting.

### Day-5 exit criterion

Two consecutive sessions have reproducible scans, no manual order choice,
clean reconciliation, and complete evidence. Draft the one-page logic/risk/
Alpaca-infrastructure narrative directly from the ledger and design spec.

## 9. Day 6 — Wednesday, Sep 2: submission freeze

- Run the unchanged system.
- Freeze code affecting alpha, strategy, risk, and order semantics by end of
  day. G5 passes.
- Produce final robustness tables from locked test and prospective shadow/live
  data; separate them clearly.
- Finish README, architecture image/diagram, setup steps, disclosures, and
  secret scan.
- Rehearse a four-minute demo:
  1. thesis and why the single-ticker approach was rejected;
  2. live P&L/risk state;
  3. one trade evidence card and one `no_trade` card;
  4. autonomous order/exit ledger;
  5. shadow counterfactuals and limitations.
- Record a backup demo while the system and data are known to work.

## 10. Day 7 — Thursday, Sep 3: final full-session run

- Operate the frozen system; no alpha tuning.
- Permit only high-severity operational fixes that preserve logged intent.
- Record the final demo during a healthy window and capture dashboard/archive
  screenshots afterward.
- Finalize the one-page write-up, video, repository, and submission fields.
- Test the public project from a clean environment with no private keys.
- Prepare an explicit wind-down checklist for Friday morning.

## 11. Deadline day — Friday, Sep 4

The event closes at 15:00 UTC / 11:00 ET, well before the market close.
Use an internal cutoff with margin; confirm organizers' final rules first.

### Internal operating policy

- No new entries after 14:00 UTC / 10:00 ET.
- Begin flattening no later than 14:15 UTC.
- Cancel all working orders and be reconciled flat by 14:30 UTC / 10:30 ET.
- Capture account equity/P&L, positions=0, orders, final ledger hash, and system
  status.
- Submit before 14:40 UTC if the form permits; preserve 20 minutes for upload
  or authentication failures.
- Do not risk a late submission to gain another few minutes of paper P&L.

If organizers explicitly score open marked positions or specify a different
wind-down rule, update this policy before Friday and record the reason. Never
leave the behavior ambiguous.

## 12. Strict descope ladder

Cut from the bottom upward. The first four items are non-cuttable.

### Never cut

1. Paper/live separation, secret safety, and kill switch.
2. Order placement, idempotency, reconciliation, monitoring, and exit.
3. Defined-risk sizing and aggregate portfolio limits.
4. Point-in-time ledger and ability to explain every number.

### Cut in this order

1. External web/Tavily news; Alpaca news is enough for MVP.
2. LLM critic or multiple specialized agents.
3. Options-flow/skew alpha if OPRA and history validation are not both present.
4. Credit spreads, condors, straddles, and strangles; keep debit verticals.
5. News alpha if the locked test fails; retain it as a shadow book.
6. Dynamic universe construction; use a disclosed static liquid list.
7. Fancy option repricing/Monte Carlo; keep exact payoff algebra and stress
   grids.
8. Rich frontend; keep one dashboard page generated from the ledger.
9. Intraday event rescans; keep fixed scheduled scans.

Never cut execution to save an analysis feature. Never loosen thresholds to
force a trade. Never add a strategy because one recent paper fill looked good.

## 13. Definition of done

### Engineering

- Clean setup on a fresh machine/environment.
- Paper endpoint enforced and live path absent.
- Alpaca integration version pinned; MLeg fallback tested.
- No committed secrets; secret scan passes.
- Restart-safe state and idempotent order IDs.
- Deterministic risk/structure/payoff unit tests pass.
- Every broker position and working order reconciles to a ledger record.

### Research

- Point-in-time feature construction documented.
- Chronological train/calibration/test split and purge documented.
- Random, price-only, news-only, and combined results present.
- Conservative cost assumptions shown beside midpoint sensitivity.
- Trial count, discarded variants, concentration, and failure cases disclosed.
- Competition outcomes are labeled prospective and not mixed into backtests.

### Product and judging

- Working autonomous prototype and reachable demo.
- P&L, open risk, health, trade/no-trade evidence, and counterfactuals visible.
- Short video, one-page write-up, public repository, and required deck/assets.
- README explains the AI role, deterministic controls, Alpaca infrastructure,
  risk gates, setup, limitations, and paper-only nature.
- Final account and submission state captured before the deadline.

## 14. Daily operator checklist

### Before arm

- Correct paper account and starting/current equity.
- No unexpected positions or orders.
- Market clock/calendar sane.
- Data and feed identities match config.
- Model, prompt, strategy, and risk hashes match the frozen manifest.
- Recorder, forecast, risk, order adapter, dashboard, and alerts healthy.
- Wind-down and kill-switch actions tested and reachable.

### After disarm

- Working orders cancelled or intentionally documented.
- Positions and broker activities reconciled.
- Broker and conservative P&L snapshots stored.
- Missing/stale data and all degraded intervals logged.
- No parameter changed because of that day's P&L.
- Submission artifacts backed up and reproducible.

This plan optimizes for a credible autonomous agent that can survive a live
demo and a short competition, not for the largest possible feature list.
