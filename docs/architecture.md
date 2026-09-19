# Architecture

## Current entry paths

ONMC has three connected paths over the existing repository service and SQLite
store. Optional integrations remain behind adapters.

```text
Claude hooks / explicit-session CLI or MCP
  -> WorkingContext: goal + constraints + notes
  -> ranked memory -> source-content checks -> whole-item budget
  -> packet fingerprint -> fresh context or no repeat

CLI / Python API / MCP
  -> OnmcService -> ingest, recall, tasks, briefs, repository-memory sync

onmc run
  -> typed task plan + cited context + policy decisions
  -> durable execution -> selected agent + configured verifier
  -> proof graph + receipt

experiment/report scripts
  -> corpus + calibration + raw artifacts -> publication gates
```

`working_context/` stores session records transactionally in the existing local
SQLite database. It hashes source contents, caches checks within a compilation,
and records explicit eligibility reasons. Hooks and MCP consume packet delivery;
CLI inspection does not. Resume/compaction forces refresh. Working notes are not
included in repository-memory exports. See [working context](working-context.md)
for trust, budget, concurrency, and best-effort delivery limits.

`harness_run/`, `runtime/`, and `durable_runtime/` provide the canonical execution
contract, backend/delegation interfaces, and durable events. `onmc run` previews
by default and executes only with `--execute`. The existing loop remains the
single-agent execution component. Optional swarm/runtime adapters do not replace
the local memory layer or establish an empirical benefit by their existence.

`experiment/` binds publication claims to corpus identity, calibration, raw
artifacts, verifier evidence, product smoke, delegation, and routing evidence.
Missing gates remain visible. A complete artifact does not itself establish
better coding outcomes. See [the current report](evidence/sota-report.md).

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
   - merges PreCompact and SessionStart (matcher `"compact"`) hooks into the
     project's `.claude/settings.json`
   - optionally registers `onmc serve --mcp` in the project's `.mcp.json`
   - migrates and cleans up legacy global installs in `~/.claude/settings.json`

10. `onmc hooks pre-compact` / `onmc hooks session-start`
   - read the hook JSON payload from stdin (`session_id`, `transcript_path`, ...)
   - pre-compact: snapshot active task state into `compaction_snapshots`,
     enriched with active files and recent assistant text parsed from the
     actual session transcript
   - session-start: when the session resumes after compaction, compile a
     continuation brief and emit the Claude Code stdout contract
     (`hookSpecificOutput.additionalContext`) so the brief is injected into
     model context; a copy is written to `.onmc/continuation-brief.md` for
     inspection only

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

17. `onmc serve --mcp [--repo PATH]`
   - serves MCP tools and resources over stdio, repo resolved once at startup
   - tools: `search_memory`, `get_brief`, `record_attempt`, `record_memory`,
     `list_tasks` — the action surface agents use mid-session
   - resources expose briefs, memory, task state, snapshots, and status

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

- MCP tool and resource server definition
- read/write memory and task tools with validated inputs
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

SQLite is used because it keeps the package dependency surface low while still supporting:

- idempotent local state
- memory queries
- repo file metadata
- ingest bookkeeping

Core tables include:

- `memories`
- `tasks`
- `attempts`
- `memory_artifacts`
- `task_outputs`
- `compaction_snapshots`
- `repo_files`
- `file_stats`
- `meta`

Manual memories use `source_type = manual` and can be recorded through the CLI,
Python API, and MCP `record_memory` tool. Working-context session records are
versioned values in the existing `meta` store, separate from durable memories.

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

### Why lexical retrieval stays the default

BM25 is the default. Optional dense and hybrid retrieval paths exist, including
local embedding integrations. On the frozen internal 40-query code corpus,
BM25 R@5 was 0.950 and hybrid 0.875. Those measurements justify the current default
on that corpus, not a universal ranking claim. See the
[retrieval results](benchmarks/results/2026-09-19-working-context/README.md).

## Current LLM Boundary

The LLM layer is now optional but materially useful:

- provider configuration is optional
- `ingest` can mine commits and docs with an LLM
- `brief` can rerank candidate memory with an LLM
- `CLAUDE.md` can be generated by an LLM or a deterministic fallback
- transcript mining can extract attempts and findings with an LLM
- `solve` / `review` / `teach` are explicit model-backed commands
- `onmc loop` invokes one installed Claude Code, Codex, or OpenCode CLI through a headless adapter
- loop verification, stopping rules, receipts, evals, and replay remain deterministic control logic
- `onmc nomistakes` composes audit, optional eval, autopilot, isolation, and receipt verification into a PR gate
- solve/review/teach are explicit model-backed commands, separate from autonomous loop execution
- secrets stay in environment variables
- every provider call is logged to `.onmc/logs/llm-calls.jsonl`

## Autonomous Loop Boundary

`onmc loop` is deliberately smaller than a generic orchestrator:

1. compile a memory-grounded prompt for one goal
2. run one selected agent adapter
3. execute one user-supplied verifier
4. record the prediction and observed outcome
5. stop on convergence, no progress, or a hard resource limit
6. write a hash-chained receipt

ONMC owns memory, control, verification, and evidence. The selected agent CLI owns code generation
and tool use. This keeps agent-specific execution replaceable and makes completion independently
testable.

`onmc nomistakes` is a higher-level gate over the same boundary. It does not add a hidden merge bot:
it runs preflight checks, delegates code generation to one selected agent, runs the verifier, and
approves only when the configured gates and verifier-backed receipt pass.

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
