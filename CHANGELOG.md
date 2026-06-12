# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Fixed

- **Claude Code hooks now target the real hook API.** The previous integration registered a `PostCompact` event that does not exist in Claude Code, wrote the continuation brief to a file nothing reads, and installed hooks globally so they fired in every repo. Hooks are now project-scoped (`.claude/settings.json`): `PreCompact` plus `SessionStart` with matcher `"compact"`, with context injected through the documented `hookSpecificOutput.additionalContext` stdout contract. Hook commands read the JSON payload Claude Code passes on stdin, and `pre-compact` enriches the compaction snapshot from the live session transcript — no manual task journaling required. Uninstall is surgical and also cleans up legacy global installs.
- **MCP registration moved to `.mcp.json`.** Claude Code never read `mcpServers` from `settings.json`; registration was silently ignored.
- **`onmc mine` now finds real transcripts.** Discovery previously used a fabricated `sha256`-hashed `sessions/` layout; it now targets the actual `~/.claude/projects/<sanitized-path>/<session-uuid>.jsonl` layout and parses the real message schema (text and `tool_use` content blocks, sidechain transcripts skipped).
- **Re-ingest no longer destroys feedback.** `onmc memory confirm`/`reject` scores (and original creation times) survive every `onmc ingest`.
- **Storage hygiene.** Connections are now closed (previously leaked in the MCP server and watch mode), WAL and a busy timeout are enabled, and schema migrations are versioned.
- OpenAI requests send `max_completion_tokens` (required by newer models) with a one-shot fallback to `max_tokens` for older ones.

### Added

- **MCP tools.** `onmc serve --mcp` now exposes `search_memory`, `get_brief`, `record_attempt`, `record_memory`, and `list_tasks` alongside the existing read-only resources, plus a `--repo` flag so the server no longer depends on its working directory.
- **LLM call retries.** Provider calls retry up to 3 attempts with exponential backoff and jitter on 429/5xx/timeouts, honoring `Retry-After`.

### Changed

- `onmc hooks post-compact` is replaced by `onmc hooks session-start` (a deprecated alias remains).
- `.onmc/logs/llm-calls.jsonl` now stores truncated prompts/responses by default (full payloads with `ONMC_LOG_FULL_PROMPTS=1`) and rotates at 10 MB.

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
