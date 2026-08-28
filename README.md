# AlphaLedger: replanned hackathon package

This package replaces the original single-ticker options recommender with an
autonomous, cross-sectional paper-trading agent. Its core claim is narrower
and more defensible:

> Combine several weak, independently observable signals; validate their
> forward-return forecasts chronologically; express only the surviving edge
> through defined-risk options; and preserve a complete evidence ledger for
> every trade and every `no_trade` decision.

## Files

- `options-alpha-agent-design.md`: product thesis, alpha model, validation,
  options construction, execution, risk, observability, and source notes.
- `hackathon-build-plan.md`: execution-first schedule from Aug 27 through the
  Sep 4 submission deadline, with gates and a strict descope ladder.
- `orchestrator-system-prompt.md`: paste-ready system prompt plus the
  structured news-labeling contract used by the deterministic pipeline.
- `claude-development-harness.md`: setup, trust boundaries, daily workflow,
  and official references for the included Claude Code development harness.
- `codex-development-harness.md`: native Codex configuration, trust flow,
  agents, hooks, command rules, skills, and official references.
- `AGENTS.md`, `.claude/`, `.codex/`, and `.agents/skills/`: one canonical
  coding-agent contract with runtime-native settings, six read-only
  specialists per harness, manual workflows, and safety hooks.
- `project-state/`: the single restart checkpoint and accepted-decision log
  shared by both development harnesses.
- `.mcp.json`: pinned Alpaca MCP configured for market data only; order tools
  are deliberately absent.
- `run_manifest.example.yaml`: secret-free Day-0 facts and frozen-run template
  referenced by the build plan.

## The consequential changes

| Original plan | Replanned system |
|---|---|
| User supplies one ticker | Agent scans a frozen liquid universe |
| Measures whether news moved the stock | Forecasts *future* residual returns |
| One event becomes the thesis | Pooled, chronological evidence across many events |
| Options are only payoff wrappers | Options data is an optional signal, enabled only when data quality supports it |
| Driftless GBM produces POP/EV | Empirical forecasts drive the trade; exact payoff algebra and stress scenarios describe the structure |
| Per-trade human confirmation | One explicit paper-only arm action, then autonomous operation within frozen limits |
| Execution is cuttable | Execution, reconciliation, exits, and risk are the first non-cuttable vertical slice |
| Tune thresholds during demo hunting | Freeze model/config before live competition runs and log every trial |

## What remains from the Sonnet draft

The useful principles were retained: deterministic mathematics and risk,
defined-risk structures, strict data and liquidity gates, real-number
traceability, an explicit `no_trade` state, and an LLM limited to tasks where
language judgment is actually useful. The event-study idea remains as a
feature; it no longer masquerades as a forward alpha by itself.

## MVP in one sentence

Scan 20 to 30 liquid optionable names, combine a market/sector-neutral
price-volume signal with point-in-time news features, trade at most the top
one or two validated directions through liquid debit verticals, and show the
trade, its counterfactual shadow books, and the risk state in a live evidence
ledger.

Paper trading only. This is a competition engineering plan, not investment
advice or a claim of future profitability.

## Joining the project

New to this repository, human or agent: read `ONBOARDING.md` first. It is the
shortest path from a clone to a merged unit and it names the rules that are
enforced by hooks rather than by convention.

## Development jump-start

Start Claude Code or Codex at the repository root and review the committed
settings and hooks. In Claude Code, inspect `/hooks` and invoke `/bootstrap`; in
Codex, inspect `/hooks` and invoke `$bootstrap`. Both harnesses load the same
design, decisions, and checkpoint. Neither scaffolds application code before
the event rules are verified or receives a raw order tool.

The first implementation session should complete G0 in
`run_manifest.example.yaml`, then build the paper endpoint assertion and typed
order-adapter contract. End useful sessions with `/handoff` in Claude Code or
`$handoff` in Codex so the next session resumes from verified state rather than
conversation memory.
