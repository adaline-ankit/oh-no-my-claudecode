# Changelog

All notable changes to this project are documented here.

## [0.3.0] — 2026-03-31

### Added

- **God Mode setup wizard** (`onmc setup`): a guided onboarding flow that detects repo shape, optionally configures an LLM provider, runs ingest, generates `CLAUDE.md`, and offers Claude Code hook/MCP/post-commit integration in one command.
- **LLM-powered ingest upgrade**: `onmc ingest` now optionally mines commit batches and docs for decisions, invariants, failed approaches, design conflicts, and gotchas, with Pydantic validation and logged provider calls.
- **`CLAUDE.md` generation and maintenance** (`onmc claude-md`): generate, preview, update, and watch a repo-specific `CLAUDE.md` synthesized from stored memory and active tasks.
- **Claude Code transcript mining** (`onmc mine`): read Claude Code assistant transcripts, exclude user turns, extract attempts and durable memory, and link findings back to tasks when possible.
- **LLM-ranked briefs**: `onmc brief` can now rerank candidate memory with task-specific relevance reasons while preserving the deterministic fallback.
- **Upgraded `teach` mode**: richer teaching output plus interactive follow-up Q&A with the same memory spine.
- **Health checks** (`onmc doctor`): audit repo state, memory freshness, provider readiness, Claude integration, and sync state from one command.
- **LLM call logging**: all provider calls are appended to `.onmc/logs/llm-calls.jsonl` with timestamps, token counts, model, and latency.

### Changed

- README and architecture docs now describe the God Mode workflow, `CLAUDE.md`, transcript mining, doctor, and optional LLM-assisted ingest/ranking.
- `teach` output now supports a richer schema while remaining backward-compatible with the earlier prompt contract.

### Fixed

- `solve` / `review` / `teach` now remain strict about provider configuration unless `--no-llm` is explicitly requested.
- Transcript-to-task linking now uses tokenized file overlap instead of exact string matching.

## [0.2.0] — 2026-03-31

### Added

- **Git-portable memory sync** (`onmc sync`): export the full memory store to `.agent-memory/` as committable JSON, restore it on any machine or cloud environment with `onmc sync --restore`, and auto-export on every commit with `onmc sync --install-hook`.
- **Claude Code compaction hooks** (`onmc hooks`): install PreCompact and PostCompact hooks that snapshot active task context before compaction and inject a continuation brief after, so Claude Code resumes without losing engineering context.
- **CompactionSnapshot model**: new first-class record type that stores active files, recent decisions, working hypothesis, last error trace, and next step at each compaction boundary.
- **Continuation brief compiler**: a purpose-built brief that answers "where were we, what did we decide, what were we trying, what's next" — distinct from the standard `onmc brief` task compiler.
- **Read-only MCP server** (`onmc serve --mcp`): exposes the full memory store as MCP resources so any MCP-compatible agent can query repo context mid-session. Resources: `onmc://brief`, `onmc://memory/*`, `onmc://tasks`, `onmc://task/{id}`, `onmc://snapshot/latest`, `onmc://status`.
- **Incremental ingest** (`onmc ingest --files`): re-ingest specific files without a full repo scan. Git hook mode via `onmc ingest --install-hook` auto-ingests changed files on every commit.
- **Public Python API** (`import onmc`): all CLI capabilities exposed as a typed importable library. `onmc.init()` returns an `OnmcRepo` with `.memory`, `.task`, `.hooks`, `.sync`, `.brief()`, and `.ingest()` surfaces. `py.typed` marker added for mypy support.

### Changed

- Quickstart updated to distinguish fresh-repo flow from clone-and-restore flow.
- README reorganized with agent integration reference table and MCP setup instructions.

### Fixed

- `.env` excluded from git tracking.

## [0.1.0] — 2026-03-24

Initial release.

- `onmc init`, `onmc ingest`, `onmc brief`
- Task and attempt lifecycle tracking
- Memory artifact recording and inspection
- Optional LLM modes: `onmc solve`, `onmc review`, `onmc teach`
- Anthropic and OpenAI provider support
- Full test suite, CI, and PyPI publishing scaffold
