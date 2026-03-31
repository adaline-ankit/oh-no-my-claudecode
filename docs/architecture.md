# Architecture

## Goals

P0 is intentionally narrow:

- local-first
- useful without an LLM
- deterministic where possible
- provenance-driven
- easy to publish as a small OSS package

The system compiles repo-specific context into a brief that a coding agent can consume before editing.

## Runtime Flow

1. `onmc setup`
   - detects repo characteristics and Claude Code presence
   - optionally configures an LLM provider
   - runs ingest, `CLAUDE.md` generation, hook install, MCP registration, and auto-sync

2. `onmc init`
   - discovers the git repo root
   - creates `.onmc/`
   - writes `.onmc/config.yaml`
   - initializes `.onmc/memory.db`

3. `onmc ingest`
   - scans repository files
   - parses selected markdown docs
   - walks git history
   - infers hotspots and validation hints
   - stores structured memory and repo metadata in SQLite
   - optionally runs an LLM extraction pass over commit batches and docs
   - validates extracted JSON before storing `llm_extracted` memory

4. `onmc ingest --files ...`
   - reprocesses only the requested files
   - updates matching doc memories and file stats
   - refreshes related git patterns for the touched paths
   - leaves unrelated memory untouched

5. `onmc sync --commit` / `onmc sync --restore`
   - exports SQLite state to `.agent-memory/` JSON + markdown
   - restores that exported state on another machine or workspace

6. `onmc task start`
   - creates a durable task record
   - captures repo root and current branch
   - initializes lifecycle timestamps and labels

7. `onmc attempt add`
   - attaches an attempt record to an existing task
   - stores status, reasoning notes, evidence, and touched files
   - preserves failed or partial paths alongside successful ones

8. `onmc brief --task "..."`
   - loads stored memory and repo metadata
   - tokenizes the task
   - ranks memory entries and file paths heuristically
   - optionally reranks the final candidate set with an LLM and annotates relevance reasons
   - builds a concise markdown brief
   - writes `.onmc/compiled/<timestamp>-brief.md`

9. `onmc hooks install`
   - merges Claude Code PreCompact and PostCompact hooks into `~/.claude/settings.json`
   - optionally adds `onmc serve --mcp` to Claude Code MCP server config

10. `onmc hooks pre-compact` / `onmc hooks post-compact`
   - serialize active task state into `compaction_snapshots`
   - compile a short continuation brief after compaction
   - write `~/.onmc-continuation-brief.md` for session recovery

11. `onmc llm configure`
   - persists optional provider settings in `.onmc/config.yaml`
   - keeps secrets in environment variables instead of local config
   - prepares a minimal generation interface for future LLM-backed features

12. prompt compilation
   - loads task records, attempts, memory artifacts, and a fresh deterministic brief
   - builds a structured prompt for `solve`, `review`, or `teach`
   - injects negative memory and validation guidance before any model call

13. `onmc solve`, `onmc review`, `onmc teach`
   - resolve the configured provider from `.onmc/config.yaml` plus environment variables
   - compile the mode-specific prompt from ONMC memory and brief context
   - request structured JSON output from the provider
   - render a concise terminal view
   - write `.onmc/compiled/<timestamp>-<mode>.md`
   - persist a task-linked output record when a task context is provided
   - `teach --interactive` re-injects the memory spine for follow-up Q&A

14. `onmc claude-md ...`
   - generate `CLAUDE.md` from stored memory and active tasks
   - update stale sections while preserving `<!-- user-written -->` sections
   - watch the memory DB and regenerate automatically on change

15. `onmc mine`
   - discover Claude Code session transcripts for the current repo
   - exclude user turns from provider payloads
   - extract attempts, decisions, failed approaches, and gotchas
   - link mined findings back to tasks when file overlap is strong enough

16. `onmc doctor`
   - audit repo state, ingest freshness, memory counts, provider config, Claude integration, and sync state
   - return a nonzero exit code only when a genuine error is detected

17. `onmc serve --mcp`
   - serves read-only MCP resources over stdio
   - exposes briefs, memory, task state, snapshots, and status on demand

## Module Responsibilities

### `core/`

- repo discovery
- lifecycle orchestration
- config + storage bootstrapping

### `models/`

- typed Pydantic models for config, memory, tasks, attempts, ingest results, file stats, and brief artifacts

### `storage/`

- SQLite-backed persistence
- memory catalog
- task catalog
- attempt catalog
- memory artifact catalog
- task output catalog
- compaction snapshot catalog
- repo file metadata
- git-derived file stats
- ingest metadata

### `ingest/`

- `repo_tree.py`
  - file-tree scanning
  - repo-shape hints
- `docs.py`
  - markdown discovery
  - heading/section extraction
  - conservative section classification
- `git_history.py`
  - commit parsing
  - hotspot detection
  - co-change pattern extraction
- `pipeline.py`
  - end-to-end ingest orchestration
  - file-scoped incremental ingest
- `llm_extractor.py`
  - commit/doc extraction prompts
  - Pydantic validation
  - conservative semantic deduplication

### `sync/`

- export SQLite-backed state to `.agent-memory/`
- restore exported state into a fresh local `.onmc/`
- install a post-commit sync hook

### `hooks/`

- Claude Code settings installation and merge logic
- compaction snapshot capture
- continuation brief compilation after compaction

### `mcp_server/`

- read-only MCP server definition
- ONMC resource listing and URI handlers

### `setup/`

- environment detection for repo + Claude Code
- interactive onboarding wizard

### `claude_md/`

- memory-to-`CLAUDE.md` generation
- section-preserving updates
- file watcher integration

### `mine/`

- Claude Code transcript discovery
- assistant-turn parsing
- transcript extraction and task linking

### `api.py`

- typed public import surface
- thin wrapper over the same service layer used by the CLI

### `brief/`

- task tokenization and scoring
- relevant memory selection
- optional LLM reranking
- impacted-file ranking
- risk and validation checklist generation
- reading-list generation

### `llm/`

- provider abstraction
- config-to-provider resolution
- optional Anthropic and OpenAI text generation
- mock provider support for tests
- shared logging for all provider calls

### `prompt/`

- mode-specific prompt compilation
- output contract generation
- memory-aware prompt sectioning for `solve`, `review`, and `teach`

### `rendering/`

- Rich terminal tables and panels for CLI output

## Storage Model

SQLite is used for P0 because it keeps the package dependency surface low while still supporting:

- idempotent local state
- memory queries
- repo file metadata
- ingest bookkeeping

P0 tables:

- `memories`
- `tasks`
- `attempts`
- `memory_artifacts`
- `task_outputs`
- `compaction_snapshots`
- `repo_files`
- `file_stats`
- `meta`

Manual memory is reserved in the schema through `source_type = manual`, even though P0 does not yet expose a write command for it.

LLM-extracted and transcript-mined memories share the same `memories` table; deterministic selection and storage remain centralized even when extraction is model-assisted.

Tasks are stored as first-class records so branch, status, timestamps, labels, and final summaries can be recovered later without depending on prior chat transcripts.

Attempts are stored as task-linked records so ONMC can preserve failed, partial, and successful approaches without requiring transcript recovery or model-based summarization.

Compaction snapshots are stored separately from task records because they capture transient working state at a specific Claude Code compaction boundary.

## Design Tradeoffs

### Why deterministic heuristics first

The tool should stay useful without paid inference. Heuristics are easier to inspect, test, and reason about for a first release.

### Why typed memory instead of raw text dumps

Typed memory makes it easier to:

- rank memories by kind
- show provenance clearly
- keep the brief compact
- avoid pretending raw transcripts are reliable project knowledge

### Why no embeddings in P0

Embeddings add infrastructure, tuning overhead, and a false sense of intelligence. Token/path overlap plus git churn is a credible first slice for a repo-local tool.

## Current LLM Boundary

The LLM layer is now optional but materially useful:

- provider configuration is optional
- `ingest` can mine commits and docs with an LLM
- `brief` can rerank candidate memory with an LLM
- `CLAUDE.md` can be generated by an LLM or a deterministic fallback
- transcript mining can extract attempts and findings with an LLM
- `solve` / `review` / `teach` are explicit model-backed commands
- there is no orchestration, tool calling, or autonomous solve loop yet
- solve/review/teach are explicit commands, not a background agent runtime
- secrets stay in environment variables
- every provider call is logged to `.onmc/logs/llm-calls.jsonl`

## Public Surface

The repo now exposes a small typed import surface:

- `onmc.init(...)`
- `OnmcRepo.ingest()`
- `OnmcRepo.brief(...)`
- `OnmcRepo.memory.*`
- `OnmcRepo.task.*`
- `OnmcRepo.hooks.*`
- `OnmcRepo.sync.*`

This is intentionally thin. The public API reuses the existing service layer instead of introducing a second architecture.
