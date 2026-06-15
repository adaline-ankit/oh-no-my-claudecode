# Changelog

All notable changes to this project are documented here.

## [Unreleased]

## [0.8.0] — 2026-06-16

### Added

- **`onmc plug <claude-code|codex|cursor|omc|omx|all>`** — one command wires onmc into a target agent (Claude Code hooks + `.mcp.json`, a Codex `AGENTS.md` stanza, a Cursor rules file, copy-paste adapters for oh-my-claudecode / oh-my-codex). Idempotent; plus `docs/integrations/` guides. Other agents adopt onmc's memory (`onmc brief`, `onmc guard`) without changing their workflow.
- **`AGENT-MEMORY-SPEC.md`** — an open, versioned specification for the `.agent-memory/` format (directory layout, record schemas + enums, identity/provenance/staleness semantics, forward-compat, conformance), so any tool can read and write one shared brain.
- **`onmc spec print` / `onmc spec validate`** — make the spec executable: validate that a `.agent-memory/` directory conforms (pass/fail with specific errors).

## [0.7.0] — 2026-06-15

### Added

- **`onmc why --at <commit>`** — time-travel: recompute a file's why-report as of a past commit (git history bounded to the commit; memory entries are labeled as reflecting the current store).
- **`onmc memory-diff <commitA> <commitB>`** — diff the committed `.agent-memory/` export between two commits (added / removed / changed memories), with a file-name-diff fallback when no brain is committed.
- **`onmc wiki [--output DIR]`** — generate a browsable multi-page knowledge wiki (index, per-subsystem pages, relationship graph) from memory + the memory-edge graph.

### Changed

- `onmc claude-md generate` now produces clean, coherent output (sentence-boundary truncation, code fences reduced to breadcrumbs, deduped source labels).
- A memory-grounded PR bot posts `onmc why` / `onmc guard` context on pull requests; the brain-freshness check is now informational (no longer shows a failing status).

## [0.6.0] — 2026-06-15

### Added

- **`onmc guard`** — failure-aware loop: surfaces recorded `failed_approach` / `did_not_work` memory for a task as explicit "DO NOT retry these dead-ends" guidance, as a CLI command and a `guard_task` MCP tool, so an agent never repeats a recorded mistake.
- **`onmc statusline` / `onmc hud`** — memory-health observability: a compact one-line statusline (mem count, freshness %, stale count, tokens/day) for Claude Code's `statusLine`, and a richer HUD panel (counts by kind, freshness bar, coverage proxy, recent LLM cost aggregated from the call log).
- **`onmc bench`** — a deterministic, reproducible proof harness comparing an agent with vs without onmc memory (built-in scenario: repeated-failure rate 100% → 0%, context tokens −97%).
- **Local embeddings rerank** — opt-in hybrid retrieval layering semantic cosine similarity over FTS5, with a dependency-free deterministic default embedder (vectors cached in SQLite, migration v6); gated by `ONMC_EMBEDDINGS`.
- **Claude Code plugin + marketplace manifest** (`.claude-plugin/`), an enhanced **AGENTS.md**, and an AI-Ready badge.
- **Dogfooding**: the repo now ships its own committed `.agent-memory/` brain plus a brain-freshness CI check.

## [0.5.0] — 2026-06-15

### Added

- **`onmc consolidate` (memory "dreaming")** — a manual command plus a SessionEnd hook that self-improves the store between sessions: dedups near-duplicate memories, merges and promotes high-feedback ones, demotes/flags stale, and builds a memory-edge graph (migration v5: `supersedes` / `contradicts` / `relates` / `duplicate_of`) surfaced in `onmc why`. Manual memories are never deleted; `--dry-run` previews.
- **`onmc tui`** — a `rich`-based interactive brain browser (Memories / Playbooks / Tasks / Status) with inline confirm/reject.
- **`onmc playbook`** — memory-derived, provenance-tracked, git-portable reusable playbooks synthesized from high-signal memory (migration v4).
- **`onmc why`** — explains why a file looks the way it does from memory + git history (deterministic core, optional LLM narrative).
- **Per-prompt surgical recall** — a UserPromptSubmit hook injecting only the memory relevant to the current prompt.
- **Dual-scope user memory** — a `~/.onmc/user.db` layer (`onmc user`) of durable preferences that travels across all repos and leads the SessionStart boot digest.
- **FTS5 hybrid memory search** and **provenance staleness** (`onmc memory verify` / `prune`, migration v3).
- **SessionStart boot digest** injecting a compact repo-memory digest at session start.

### Changed

- **MCP output is now TOON by default** (~50% fewer tokens than JSON for record lists); JSON via `ONMC_MCP_FORMAT=json` or `?format=json`. SQLite and `.agent-memory/` export stay JSON.
- **Tag-driven release pipeline**: pushing `vX.Y.Z` runs the gate, builds, and creates a GitHub Release; the PyPI publish job is gated behind `vars.PYPI_TRUSTED_PUBLISHING` and skips (does not fail the run) until trusted publishing is configured. See `docs/RELEASING.md`.

## [0.4.0] — 2026-06-15

### Fixed

- **Claude Code hooks now target the real hook API.** The previous integration registered a `PostCompact` event that does not exist in Claude Code, wrote the continuation brief to a file nothing reads, and installed hooks globally so they fired in every repo. Hooks are now project-scoped (`.claude/settings.json`): `PreCompact` plus `SessionStart` with matcher `"compact"`, with context injected through the documented `hookSpecificOutput.additionalContext` stdout contract. Hook commands read the JSON payload Claude Code passes on stdin, and `pre-compact` enriches the compaction snapshot from the live session transcript — no manual task journaling required. Uninstall is surgical and also cleans up legacy global installs.
- **MCP registration moved to `.mcp.json`.** Claude Code never read `mcpServers` from `settings.json`; registration was silently ignored.
- **`onmc mine` now finds real transcripts.** Discovery previously used a fabricated `sha256`-hashed `sessions/` layout; it now targets the actual `~/.claude/projects/<sanitized-path>/<session-uuid>.jsonl` layout and parses the real message schema (text and `tool_use` content blocks, sidechain transcripts skipped).
- **Re-ingest no longer destroys feedback.** `onmc memory confirm`/`reject` scores (and original creation times) survive every `onmc ingest`.
- **Storage hygiene.** Connections are now closed (previously leaked in the MCP server and watch mode), WAL and a busy timeout are enabled, and schema migrations are versioned.
- **`onmc init` now gitignores `.onmc/`.** The docs always claimed the local state dir was gitignored, but nothing enforced it — a `git add -A` would commit the binary SQLite store and the LLM call log (which can contain repo source). Init now adds an idempotent `.onmc/` entry to the repo's `.gitignore`. Only the JSON export under `.agent-memory/` is meant to travel with the repo.
- **MCP startup banner** told users to register the server in `settings.json`, which Claude Code ignores; it now shows `claude mcp add` and the project `.mcp.json` form.
- OpenAI requests send `max_completion_tokens` (required by newer models) with a one-shot fallback to `max_tokens` for older ones.

### Added

- **MCP tools.** `onmc serve --mcp` now exposes `search_memory`, `get_brief`, `record_attempt`, `record_memory`, and `list_tasks` alongside the existing read-only resources, plus a `--repo` flag so the server no longer depends on its working directory.
- **LLM call retries.** Provider calls retry up to 3 attempts with exponential backoff and jitter on 429/5xx/timeouts, honoring `Retry-After`.
- **End-to-end test suite** (`tests/test_e2e.py`) drives the real `onmc` binary as a subprocess through the full memory lifecycle, the Claude Code hook stdin/stdout contracts, transcript-mining discovery, a `sync`→clone→`restore` roundtrip, and a real MCP stdio client/server handshake.
- **FTS5 full-text search** on memory artifacts for fast keyword queries across stored knowledge.
- **Staleness detection** marks memory entries as stale when the files they reference have changed since ingest.
- **Boot digest** (`onmc hooks session-start`) compiles a compact ≤400-token repo brain summary injected at every Claude Code session start.

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
