# Shipped Capabilities

This document is the fastest way for a human or coding agent to understand what ONMC currently ships.

It answers four questions:

1. What ONMC is
2. What features are implemented right now
3. How the pieces fit together
4. Which workflows are intended versus out of scope

## What ONMC Is

`oh-no-my-claudecode` is a repo-native memory and context layer for coding agents.

It is not just a prompt pack and it is not yet a generic multi-agent runtime.

Today ONMC does four core things:

- builds deterministic repo memory from docs, git history, and file structure
- optionally uses an LLM to extract and rank higher-signal memory where heuristics are weak
- stores durable task-scoped engineering memory in local SQLite state
- compiles high-signal briefs and prompts for coding work
- exposes that memory to agents through CLI commands, a Python API, Claude Code hooks, and a read-only MCP server

## What Is Implemented

### 0. Setup Wizard

The recommended onboarding flow is now:

```bash
onmc setup
```

The wizard can:

- initialize `.onmc/`
- configure an optional provider
- ingest repo memory
- generate `CLAUDE.md`
- install Claude Code hooks
- register the MCP server
- install post-commit ingest/sync automation

### 1. Repo Memory Ingest

ONMC can initialize local state and ingest repo knowledge with:

```bash
onmc init
onmc ingest
```

What gets stored:

- markdown-derived facts, decisions, invariants, and validation rules
- git-derived hotspots and co-change patterns
- repo-tree-derived validation and layout hints
- repo file metadata and git file stats

If a provider is configured, ingest now adds an LLM extraction pass over commit batches and docs.
Those extractions are validated before storage and written as `llm_extracted` memory with
confidence scores.

Stored under:

- `.onmc/config.yaml`
- `.onmc/memory.db`
- `.onmc/compiled/`

### 2. Incremental Ingest

ONMC can reprocess only selected files:

```bash
onmc ingest --files README.md docs/architecture.md
```

What this updates:

- matching doc memories for those files
- matching repo file records
- matching file stats
- related git-pattern memories for the touched paths

It does not yet do stale-memory pruning.

### 3. Task Lifecycle

Tasks are first-class records:

```bash
onmc task start --title "Fix cache bug" --description "Track the flaky path"
onmc task list
onmc task show <task_id>
onmc task status <task_id> --status blocked
onmc task end <task_id> --status solved --summary "Fixed at the cache boundary"
```

Task records persist:

- task id
- title and description
- lifecycle status
- timestamps
- repo root and branch
- labels
- final summary / outcome fields

### 4. Attempt Logging

Attempts preserve what was tried, including partial or failed approaches:

```bash
onmc attempt add <task_id> --summary "Try a cache-only fix" --kind fix_attempt --status tried
onmc attempt list <task_id>
onmc attempt show <attempt_id>
onmc attempt update <attempt_id> --status rejected --evidence-against "Did not touch the failing path"
```

Attempts store:

- summary
- kind
- status
- reasoning summary
- evidence for / against
- files touched
- creation / close timestamps

### 5. Task-Derived Memory Artifacts

Tasks can produce durable reusable artifacts:

```bash
onmc memory add <task_id> --type fix --title "Use the cache boundary" --summary "The shared boundary fixed the worker path"
onmc memory list
onmc memory list --type did_not_work
onmc memory show <memory_id>
```

Artifact types:

- `fix`
- `did_not_work`
- `design_conflict`
- `gotcha`
- `invariant`
- `validation`

These are explicitly provenance-linked to the task that produced them.

### 6. Brief Compilation

ONMC compiles a task-specific deterministic brief:

```bash
onmc brief --task "fix flaky Redis cache invalidation bug"
```

The brief includes:

- task summary
- repo overview
- relevant memory
- likely impacted areas
- files to inspect first
- risk notes
- validation checklist
- provenance

The markdown artifact is written to `.onmc/compiled/<timestamp>-brief.md`.

When a provider is configured, ONMC reranks the final candidate memory set with an LLM and stores
one-sentence relevance reasons in the brief output.

### 7. Optional LLM Layer

ONMC can optionally call a configured provider:

```bash
onmc llm configure --provider anthropic --model <model-id>
onmc llm status
```

Supported providers:

- Anthropic
- OpenAI
- Mock provider for tests

Secrets are read from environment variables, not stored in config.

### 8. Prompt Compiler and Agent Modes

ONMC has three prompt modes:

- `solve`
- `review`
- `teach`

Commands:

```bash
onmc solve --task "..." [--task-id ...]
onmc review --task "..." [--input-file ...]
onmc teach --task "..." [--task-id ...]
```

What they do:

- `solve` proposes the next engineering approach using task memory, repo brief, failed attempts, and validation guidance
- `review` critiques a proposed fix or plan for assumptions, regressions, and missing checks
- `teach` explains the reasoning path, false leads, and reusable engineering lesson

Outputs are:

- rendered in the terminal
- written under `.onmc/compiled/`
- persisted as task-linked output records when a task context is provided

`teach --interactive` can continue the explanation as a follow-up Q&A loop with the same memory
spine re-injected each turn.

### 9. `CLAUDE.md` Generation

ONMC can generate and maintain agent bootstrap context directly:

```bash
onmc claude-md generate
onmc claude-md preview
onmc claude-md update
onmc claude-md --watch
```

Generated sections cover project overview, invariants, decisions, hotspots, bad approaches,
validation, and active tasks.

### 10. Claude Code Transcript Mining

ONMC can mine Claude Code transcripts:

```bash
onmc mine
onmc mine --dry-run
onmc mine --since "2 days ago"
```

This reads assistant turns only, excludes user turns from provider payloads, and extracts attempts,
decisions, failed approaches, and gotchas.

### 11. Git-Portable Memory Sync

ONMC can export and restore state in a git-committable format:

```bash
onmc sync --commit
onmc sync --restore
onmc sync --install-hook
```

Export format:

```text
.agent-memory/
  manifest.json
  memories/
  tasks/
  compiled/latest-brief.md
```

This allows memory to move with the repo instead of staying trapped in `.onmc/memory.db`.

### 12. Claude Code Compaction Hooks

ONMC can install Claude Code compaction hooks:

```bash
onmc hooks install
onmc hooks status
onmc hooks uninstall
```

Internal hook commands:

- `onmc hooks pre-compact`
- `onmc hooks post-compact`

What they do:

- before compaction, snapshot active task context into `compaction_snapshots`
- after compaction, compile a continuation brief and write `~/.onmc-continuation-brief.md`

This is ONMC's first continuity mechanism for recovering context after compaction.

### 13. Read-Only MCP Server

ONMC can serve memory over MCP:

```bash
onmc serve --mcp
```

Exposed resources:

- `onmc://brief`
- `onmc://memory/list`
- `onmc://memory/{kind}`
- `onmc://memory/search?files=...`
- `onmc://tasks`
- `onmc://task/{id}`
- `onmc://snapshot/latest`
- `onmc://status`

This is read-only in the current release.

### 14. Health Check

```bash
onmc doctor
```

The doctor command audits initialization, ingest freshness, provider setup, Claude integration,
`CLAUDE.md`, `.agent-memory/`, and post-commit hooks, and returns a nonzero exit code only for
actual errors.

### 12. Public Python API

ONMC is now usable as a library:

```python
import onmc

repo = onmc.init(".")
repo.ingest()
brief = repo.brief(task="fix the cache invalidation bug")
memories = repo.memory.search(files=["src/cache.py"])
task = repo.task.start(title="Fix cache bug", description="Track the failing path.")
repo.sync.commit()
```

Public surface:

- `onmc.init(...)`
- `OnmcRepo.ingest()`
- `OnmcRepo.brief(...)`
- `OnmcRepo.memory.*`
- `OnmcRepo.task.*`
- `OnmcRepo.hooks.*`
- `OnmcRepo.sync.*`

## How The Pieces Fit Together

The system is designed as a memory spine with multiple front doors:

1. Ingest builds deterministic repo memory into SQLite.
2. Task, attempt, and artifact commands add durable engineering memory.
3. `brief` compiles repo-aware context from that stored memory.
4. `solve` / `review` / `teach` compile prompts from the same memory spine and optionally call an LLM.
5. `sync` makes that state portable across machines and cloud workspaces.
6. `hooks` preserve short-term working context across Claude Code compaction.
7. `serve --mcp` exposes the same state to MCP-compatible agents mid-session.
8. `import onmc` exposes the same capabilities programmatically.

## What ONMC Does Not Yet Do

Important boundaries:

- no autonomous multi-agent orchestration runtime
- no tool-calling loop
- no background solve mode
- no vector database or embedding search
- no hosted sync or remote collaboration
- no automatic stale-memory pruning
- MCP is read-only for now

## Recommended Mental Model

Use ONMC as:

- a repo memory database
- a task memory ledger
- a deterministic brief compiler
- an optional LLM reasoning layer on top of stored memory
- a continuity layer for compaction and fresh clones

Do not treat it as:

- a replacement for your coding agent
- a cloud control plane
- a generic autonomous agent framework

## Best End-to-End Workflow

For normal coding work:

```bash
onmc init
onmc ingest
onmc task start --title "..." --description "..."
onmc attempt add <task_id> --summary "..." --kind investigation --status tried
onmc brief --task "..."
onmc solve --task "..." --task-id <task_id>
onmc memory add <task_id> --type did_not_work --title "..." --summary "..."
onmc task end <task_id> --status solved --summary "..."
onmc sync --commit
```

For Claude Code:

```bash
onmc hooks install
onmc serve --mcp
```

For a fresh machine or cloud workspace:

```bash
onmc init
onmc sync --restore
onmc brief --task "..."
```
