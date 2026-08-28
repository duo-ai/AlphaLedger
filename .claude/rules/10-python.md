---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
  - "pyproject.toml"
---

# Python implementation rules

- Target Python 3.12 and manage dependencies with `uv`; commit and honor the
  lockfile. Pin broker, MCP, model, and schema-sensitive dependencies.
- Type public functions and domain boundaries. Prefer small immutable domain
  objects over dictionaries once data crosses an adapter boundary.
- Use timezone-aware UTC datetimes internally. Convert exchange sessions with
  a calendar library, never fixed UTC offsets.
- Keep side effects at adapters. Domain calculations must be deterministic,
  pure where practical, and testable without network access.
- Use `Decimal` for order prices and cash/payoff arithmetic. Quantized array
  math may use floating point when tolerances are explicit and tested.
- Make retries bounded and classified. Never retry an ambiguous order submit
  until reconciliation by client order ID proves it absent.
- Structured logs must omit article bodies and secrets by default and include
  run, decision, model, config, and correlation identifiers.
