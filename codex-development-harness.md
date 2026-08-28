# Codex development harness

This package includes a project-scoped Codex harness so implementation can
start with AlphaLedger's architecture, safety boundary, specialist reviews,
manual gate workflows, and restart state already available. It does not
scaffold the application before G0 permits it and does not imply that any
competition gate has passed.

## Layout

| Path | Purpose |
|---|---|
| `AGENTS.md` | Canonical project contract discovered by Codex |
| `.codex/config.toml` | Shared sandbox, approval, subagent, and market-data MCP configuration |
| `.codex/agents/` | Six bounded, read-only research and review roles |
| `.codex/hooks.json` | Project `PreToolUse` registration |
| `.codex/hooks/guard.py` | Contextual blocker for secrets, destructive actions, live endpoints, and Alpaca mutations |
| `.codex/rules/default.rules` | Experimental command policy for destructive and user-controlled actions |
| `.agents/skills/` | Explicit bootstrap, gate, smoke-test, handoff, and submission workflows |
| `project-state/` | Tool-neutral committed checkpoint and accepted decision log |
| `run_manifest.example.yaml` | Secret-free Day-0 and frozen-run template |

Codex skills deliberately live under `.agents/skills/`, not `.codex/skills/`.
That is the documented project-skill discovery path. The `.codex/` directory
holds project configuration, hooks, rules, and custom-agent TOML files.

## First use

1. Install a current Codex CLI or open the project in the Codex app. Install
   Python 3.12 and `uv`/`uvx`.
2. Start at the repository root so root instructions, project skills, and
   project configuration resolve as intended:

   ```bash
   cd options-alpha-agent-hackathon
   codex
   ```

3. Review `AGENTS.md`, `.codex/config.toml`, `.codex/hooks.json`, and the guard
   before trusting the project. Project-scoped configuration, hooks, and rules
   are ignored for untrusted projects.
4. In Codex, inspect `/hooks` and approve the reviewed project hook. Hooks are
   code execution and should not be trusted by filename alone.
5. Put paper credentials in the process environment or an OS secret manager.
   Do not create a repository `.env` and never paste values into chat:

   ```text
   ALPACA_API_KEY
   ALPACA_SECRET_KEY
   ```

6. Run `codex mcp list` and confirm that `alpaca` connects. Its committed
   `ALPACA_TOOLSETS` includes market data only; it omits account, trading, and
   watchlist mutation.
7. Invoke `$bootstrap`. Resolve every safety, trust, version, or MCP-scope
   failure before scaffolding code.

The project config forwards only the two named credential variables to the MCP
process; their values are not stored in TOML. The server remains optional so a
missing key cannot prevent offline code and fixture work.

## Native Codex mapping

The harness is intentionally not a file-for-file rename of `.claude/`:

| Concern | Codex primitive |
|---|---|
| Persistent project instructions | root `AGENTS.md`; nested `AGENTS.override.md` only when a subtree needs narrower rules |
| Custom specialist | `.codex/agents/<name>.toml` |
| Reusable workflow | `.agents/skills/<name>/SKILL.md`, invoked as `$name` |
| Shared runtime settings and MCP | `.codex/config.toml` |
| Event-driven contextual check | `.codex/hooks.json` plus an executable guard |
| Command escalation policy | `.codex/rules/*.rules` |

No model is pinned at project or specialist level. Specialists inherit the
parent session's available model while requesting high reasoning effort and a
read-only sandbox. This avoids coupling the repository to a model name that
may not be enabled for every developer.

## Agent model

Custom roles are bounded reviewers, not a second autonomous trading system:

| Agent | Use |
|---|---|
| `quant_researcher` | hypothesis, point-in-time evidence, falsification |
| `backtest_auditor` | leakage, purging, trials, costs, empirical claims |
| `execution_safety_reviewer` | order, risk, reconciliation, restart, kill switch |
| `alpaca_docs_researcher` | current official schemas and integration facts |
| `code_reviewer` | bounded implementation diff |
| `submission_reviewer` | frozen demo, evidence, reproducibility, claims |

The main session owns edits. Parallel subagents are appropriate for independent
read-heavy questions; they must not concurrently mutate the checkout. A
read-only role remains defense in depth because a parent session launched with
broader runtime overrides can supersede inherited sandbox behavior.

## Permissions and enforcement

The shared baseline uses `workspace-write` with approvals on request. The rule
file forbids destructive cleanup and reset commands and prompts for git
mutation, dependency-lock changes, and the application paper-smoke command
when those commands request execution beyond the sandbox.

The `PreToolUse` hook separately inspects shell commands, patch content, file
paths, and Alpaca MCP tool names. It exits with code 2 to block:

- reads, writes, or patches targeting environment, credential, or private-key
  files;
- destructive filesystem, system, and git commands;
- the live Alpaca host, disabled paper mode, or a `--live` application path;
- shell expansion of Alpaca credential variables;
- patches that broaden committed Alpaca MCP scope to account, trading, or
  watchlists; and
- mutating Alpaca MCP operations.

Test the guard without launching Codex:

```bash
python3 .codex/hooks/guard.py --self-test
```

Rules and hooks are defense in depth, not an operating-system security
boundary. Keep live-money credentials out of this project and review every
project hook before trust.

## Alpaca separation of duties

The Codex MCP server is pinned to `alpaca-mcp-server==2.3.0` and exposes only:

```text
assets,stock-data,options-data,corporate-actions,news
```

G0 account checks and G1 paper orders go through the application's typed
adapter, where endpoint assertions, risk approval, idempotency, reconciliation,
and ledger records can be tested. Do not add `account`, `trading`, or
`watchlists` to committed MCP scope. A Day-0 version change requires a recorded
decision and contract-test evidence.

## Manual skills

| Skill | When | Boundary |
|---|---|---|
| `$bootstrap` | clone or toolchain change | inspection and validation only |
| `$research-gate` | before Gate G3 freeze | audit only; cannot arm trading |
| `$paper-smoke dry-run` | before G1 | builds evidence, never submits |
| `$paper-smoke submit` | one-contract G1 test | exact acknowledgement and app-only order path |
| `$handoff` | useful session checkpoint | edits shared state, no git mutation |
| `$submission-readiness` | G5/G6 | audit only; no submission or broker mutation without a separate request |

Descriptions explicitly require user invocation because Codex discovers and
may otherwise select skills by their descriptions. The exact acknowledgement
inside `$paper-smoke submit` is an additional, in-session gate.

## Desktop local environment

Codex desktop can generate a project local-environment configuration from its
environment UI. This package intentionally does not invent that generated file
before `pyproject.toml`, `uv.lock`, and the real run commands exist. After G0
permits scaffolding, create it through the Codex UI and configure only the
documented setup and maintenance commands; keep secrets in environment or OS
secret storage.

## Official references used

- Configuration basics: <https://developers.openai.com/codex/config-basic>
- `AGENTS.md` discovery: <https://developers.openai.com/codex/agent-configuration/agents-md>
- Custom subagents: <https://developers.openai.com/codex/agent-configuration/subagents>
- Project skills: <https://developers.openai.com/codex/build-skills>
- Hooks: <https://developers.openai.com/codex/hooks>
- Execution rules: <https://developers.openai.com/codex/rules>
- MCP configuration: <https://developers.openai.com/codex/mcp>
- Local environments: <https://developers.openai.com/codex/environments/local-environment>
- Alpaca MCP server: <https://docs.alpaca.markets/us/docs/alpaca-mcp-server>
- Official Alpaca MCP repository: <https://github.com/alpacahq/alpaca-mcp-server>

The harness reflects those sources as reviewed on 2026-08-27. Recheck
version-sensitive fields before kickoff.
