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

1. `onmc init`
   - discovers the git repo root
   - creates `.onmc/`
   - writes `.onmc/config.yaml`
   - initializes `.onmc/memory.db`

2. `onmc ingest`
   - scans repository files
   - parses selected markdown docs
   - walks git history
   - infers hotspots and validation hints
   - stores structured memory and repo metadata in SQLite

3. `onmc task start`
   - creates a durable task record
   - captures repo root and current branch
   - initializes lifecycle timestamps and labels

4. `onmc attempt add`
   - attaches an attempt record to an existing task
   - stores status, reasoning notes, evidence, and touched files
   - preserves failed or partial paths alongside successful ones

5. `onmc brief --task "..."`
   - loads stored memory and repo metadata
   - tokenizes the task
   - ranks memory entries and file paths
   - builds a concise markdown brief
   - writes `.onmc/compiled/<timestamp>-brief.md`

6. `onmc llm configure`
   - persists optional provider settings in `.onmc/config.yaml`
   - keeps secrets in environment variables instead of local config
   - prepares a minimal generation interface for future LLM-backed features

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

### `brief/`

- task tokenization and scoring
- relevant memory selection
- impacted-file ranking
- risk and validation checklist generation
- reading-list generation

### `llm/`

- provider abstraction
- config-to-provider resolution
- optional Anthropic and OpenAI text generation
- mock provider support for tests

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
- `repo_files`
- `file_stats`
- `meta`

Manual memory is reserved in the schema through `source_type = manual`, even though P0 does not yet expose a write command for it.

Tasks are stored as first-class records so branch, status, timestamps, labels, and final summaries can be recovered later without depending on prior chat transcripts.

Attempts are stored as task-linked records so ONMC can preserve failed, partial, and successful approaches without requiring transcript recovery or model-based summarization.

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

The LLM layer is intentionally narrow in this step:

- provider configuration is optional
- generation is not wired into `brief`, `ingest`, or task execution yet
- there is no orchestration, tool calling, or solve mode
- secrets stay in environment variables
