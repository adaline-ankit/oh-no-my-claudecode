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
- token-efficient compact/caveman briefs and codegraph navigation
- local visual dashboard for memory, tasks, codegraph, and health
- portable single-file dashboard snapshots for demos and handoffs
- Obsidian vault export with provenance notes and memory relationship links
- optional LLM-powered commit/doc extraction during ingest
- optional LLM reranking for briefs
- `CLAUDE.md` generation, update, and watch mode
- Claude Code transcript mining
- `onmc doctor` health check
- `onmc report` shareable agent-readiness report
- incremental ingest for selected files + post-commit hook
- memory inspection commands
- tests, linting, coverage reporting, CI, and packaging scaffolding
- PyPI release workflow with trusted publishing scaffold
- OSS contributor guardrails, issue templates, Dependabot, labels, and branch protection
- CodeQL, OpenSSF Scorecard, dependency audit, and Windows smoke CI
- generated CLI reference checked in CI
- guided setup with first useful recall and dashboard handoff
- evolving cross-repo user profile and MCP profile access
- memory federation with configured multi-source pull
- knowledge coverage suggestions and deterministic stubs
- memory-grounded autonomous loop with real Claude Code and Codex adapters
- verifier-based completion and hard iteration/token/cost/wall/no-progress limits
- tamper-evident hash-chained run receipts
- Agent Trace Observatory with JSON/OpenTelemetry export
- measured/sim-labelled benchmark suite
- agent-configuration security audit and CI gate
- deterministic memory eval suite and regression gate
- deterministic trace replay with memory-vs-cold comparison
- MCP trust policy and call classification for hooks/CI
- memory-aware GitHub Agentic Workflow scaffolding

## Next

- signed receipts or optional external attestation
- live MCP transport enforcement in addition to offline/stdin classification
- richer Codex usage/cost extraction where its CLI exposes stable fields
- isolated worktree mode for autonomous loops
- real-world benchmark fixtures and opt-in published case studies
- richer test-mapping heuristics
- branch-aware briefing
- richer Claude Code session-state capture beyond compaction snapshots
- smarter transcript-to-task linking
- richer `CLAUDE.md` merge semantics
- provider-side model validation and discovery
- turn Windows smoke coverage into full Windows support
- add release notes automation around `CHANGELOG.md`

## Later

- diff-aware ingest
- explicit ADR parsing
- configurable ranking weights
- agent-facing output presets for different coding tools
- cross-runtime mission handoff without becoming a generic swarm runtime

## Explicit Non-Goals

These are not planned for the MVP path:

- hosted dashboard
- remote sync
- auth
- vector database as a requirement
- generic multi-agent orchestration runtime
- hosted agent execution
