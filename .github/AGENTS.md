# Repo automation & agents

How autonomous automation is wired on this repo, and the one-time settings that
turn each piece on. Everything here acts on GitHub events with write access —
i.e. it works while you're away.

## Already active (event agents & bots)

| Workflow | Fires on | Does |
|---|---|---|
| `ci.yml` | push, PR | ruff + mypy + pytest matrix (3.11–3.13), windows smoke, package build |
| `codeql.yml` | push, PR, schedule | CodeQL security analysis |
| `security-audit.yml` | push, PR | dependency / SARIF security audit |
| `labeler.yml`, `triage.yml` | PR / issue | auto area + priority/kind/size/risk labels |
| `pr-memory-context.yml`, `brain-freshness.yml` | PR | onmc memory context comment + freshness check |
| `scorecard.yml` | schedule | OpenSSF scorecard |
| `stale.yml`, `greetings.yml` | schedule / first-timer | housekeeping |
| `release.yml` | tag `v*` | build + publish the GitHub release |
| Dependabot | schedule | dependency-bump PRs |

## Added here

### `automerge.yml` — native auto-merge (no secret)
Enables GitHub's built-in auto-merge on the owner's PRs (or any PR labeled
`automerge`). GitHub merges the PR itself once required checks pass — retiring
manual merge scripts and the merge-race problem entirely.

**One-time settings to make it effective:**
1. **Settings → General → Pull Requests → "Allow auto-merge"** → ON.
2. **Settings → Branches (or Rules → Rulesets) → protect `main`** and mark these
   status checks **Required**:
   `quality (3.11)`, `quality (3.12)`, `quality (3.13)`, `CodeQL`.
   Without required checks, auto-merge merges immediately (defeats the point).

### `claude.yml.disabled` — @claude mention agent (needs secret; OFF by default)
A coding agent you trigger by commenting `@claude …` on an issue/PR. Inert until:
1. Add secret **`ANTHROPIC_API_KEY`** (Settings → Secrets and variables → Actions).
2. Install the **Claude GitHub App**: https://github.com/apps/claude
3. `git mv .github/workflows/claude.yml.disabled .github/workflows/claude.yml`

Pairs with auto-merge: `@claude implement X` → agent opens PR → checks go green →
PR self-merges.

## Not wired (and why)
- **`onmc prbadge` in CI** — `prbadge` reads local `.agent-memory/receipts/`, which
  don't exist in a fresh CI checkout, so it would only ever post a zero-state
  badge. It stays a local/CLI command; not worth a no-op workflow.
- **Copilot coding agent** — assign issues to `@copilot` from the GitHub UI if you
  want a second autonomous coder alongside Codex; no workflow file needed.
