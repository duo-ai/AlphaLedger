---
name: unit-006-httpx-allowlist
description: what UNIT-006 actually froze into tests/test_dependencies.py, for re-checking when UNIT-031 and UNIT-028 add the two allowlisted files
metadata:
  type: project
---

UNIT-006 (round one, reviewed 2026-09-04, commit `f1dccdb` on
`feature/006-http-dependency`) pinned `httpx==0.28.1` and added
`tests/test_dependencies.py`. It resolved C7 from the feature 001 Codex
analysis by replacing a repository-wide "no file imports httpx" prohibition
with an allowlist, `HTTPX_ALLOWLIST = {"alphaledger/broker/http.py",
"alphaledger/data/http.py"}`, hardcoded in the test file, naming two files
that do not exist yet.

**Why this matters later:** when UNIT-031 (the paper broker client) adds
`broker/http.py`, or UNIT-028 (the market-data adapter) adds `data/http.py`,
this test file (`tests/test_dependencies.py`) does not need to change for the
import itself to pass, by design, so it will not show up in either unit's
diff. Do not read that absence as those units having skipped the check; the
check ran and passed by construction, forward-declared here.

**How to apply:** when reviewing UNIT-031 or UNIT-028, re-run
`uv run pytest tests/test_dependencies.py -q` on that unit's branch and
confirm `test_httpx_is_imported_only_from_the_allowlisted_adapters` still
reports the actual importer as one of the two allowlisted paths, not a third
file. Also re-run the [[ast-import-gate-testing]] attack (a scratch
`importlib.import_module("httpx")` call) against whichever new file lands,
since that gap was reported HIGH in UNIT-006's round one and its fix status
should be checked rather than assumed.

The docstring in that file says "one HTTP client is reachable from one
place," but the allowlist itself names two files, one per concern (order path
vs. market data). That is not a defect, just loose phrasing; do not mistake a
future third allowlist entry for automatically wrong until you check what
concern it serves.
