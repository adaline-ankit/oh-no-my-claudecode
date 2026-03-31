# Changelog

All notable changes to this project are documented here.

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
