# Roadmap

## P0

Shipped in this repo:

- `onmc setup` onboarding wizard
- installable Python package
- repo-local `.onmc/` state
- SQLite memory store
- task lifecycle foundation
- task attempt logging
- git-portable `.agent-memory/` sync
- Claude Code compaction hooks + continuation snapshots
- typed public Python API
- MCP server (tools + resources)
- doc ingestion
- git-history ingestion
- hotspot and git-pattern extraction
- task brief compilation
- optional LLM-powered commit/doc extraction during ingest
- optional LLM reranking for briefs
- `CLAUDE.md` generation, update, and watch mode
- Claude Code transcript mining
- `onmc doctor` health check
- incremental ingest for selected files + post-commit hook
- memory inspection commands
- tests, linting, coverage reporting, CI, and packaging scaffolding
- PyPI release workflow with trusted publishing scaffold
- OSS contributor guardrails, issue templates, Dependabot, labels, and branch protection
- CodeQL, OpenSSF Scorecard, dependency audit, and Windows smoke CI
- generated CLI reference checked in CI

## P1

- manual memory CRUD
- stale-entry pruning by source fingerprint
- richer test-mapping heuristics
- branch-aware briefing
- richer Claude Code session-state capture beyond compaction snapshots
- smarter transcript-to-task linking
- richer `CLAUDE.md` merge semantics
- provider-side model validation and discovery
- turn Windows smoke coverage into full Windows support
- add release notes automation around `CHANGELOG.md`

## P2

- diff-aware ingest
- explicit ADR parsing
- configurable ranking weights
- agent-facing output presets for different coding tools
- deeper autonomous agent orchestration on top of the memory spine

## Explicit Non-Goals

These are not planned for the MVP path:

- hosted dashboard
- remote sync
- auth
- vector database as a requirement
- generic multi-agent orchestration runtime
- autonomous patching engine
