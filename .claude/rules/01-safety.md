# Global safety rules

- Paper trading is a compile-time and runtime boundary. Never add a live host,
  live credential path, or generic `paper=false` switch.
- Treat `.env`, secret stores, credential files, private keys, transcripts, and
  logs as sensitive. Refer to variable names only; never expose values.
- Raw Claude/Alpaca MCP tools are market-data-only. Orders flow through tested
  application code after explicit human arming and deterministic risk checks.
- Any uncertainty about endpoint, account, clock, quote freshness, feed,
  position state, order state, model/config hash, or risk state produces a
  fail-closed halt or `no_trade`.
- Money, quantity, price, strike, payoff, and risk use explicit decimal or
  integer types with declared rounding. LLM prose is never a numeric source.
- Do not mutate frozen alpha, thresholds, universe, risk limits, or strategy
  allowlists during a competition session.
- Preserve an append-only audit path for decisions and state transitions.
