# Git workflow rules

AlphaLedger uses the Git Flow branching model (Driessen). `git-flow` itself is
optional; the model is mandatory. Run `scripts/gitflow-init.sh` once per clone
and once per worktree so branch names and prefixes resolve identically for
everyone.

## Branches

| Branch | Role | Branches from | Merges into |
|---|---|---|---|
| `main` | production, always releasable | none | none |
| `develop` | integration, latest delivered work | `main` at init | none |
| `feature/*` | one unit of work | `develop` | `develop` |
| `bugfix/*` | defect against unreleased work | `develop` | `develop` |
| `release/*` | stabilise a version | `develop` | `main` and `develop` |
| `hotfix/*` | urgent production defect | `main` | `main` and `develop` |
| `support/*` | maintenance of an older line | `main` | none |

One unit in `specs/units/` is one `feature/` branch, named
`feature/<unit-id>-<slug>`, developed in its own worktree.

## Rules

- Never commit directly to `main`. It only receives `--no-ff` merges from
  `release/*` and `hotfix/*`, and every such merge is tagged `v<version>`.
- Never commit directly to `develop`, with one exception: a registry claim is a
  single-file commit to `develop`, pushed immediately so the window in which
  two people can claim the same unit stays small.
- Merge into `develop` and `main` with `--no-ff` so the branch history of a
  unit stays visible after the branch is deleted.
- Rebase a `feature/` branch onto `develop` before opening a pull request. Do
  not merge `develop` into a feature branch.
- Never force-push `main`, `develop`, or any branch another person has checked
  out in a worktree.
- A `feature/` branch merges only after the reviewer named in its unit intake
  frontmatter has reported and the repository quality gate passes.
- A `hotfix/` that lands on `main` is back-merged into `develop` in the same
  session, or the fix is lost at the next release.

## Commit messages

- One commit does one thing. The subject says which thing, in the imperative,
  under about 72 characters.
- Add a body only when the reason is not visible in the diff, and keep it to a
  few plain lines. A commit body is not a design document; that belongs in the
  unit intake under `specs/units/`.
- Never write an AI attribution trailer, a `Co-Authored-By` line naming a
  model, a "Generated with" line, or a robot emoji. The guard hook blocks these.
- Do not use em dashes or en dashes in commit messages or in project prose. Use
  a comma, a colon, or two sentences.
