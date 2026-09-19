# Shipped Capabilities

This document is the fastest way for a human or coding agent to understand what ONMC currently ships.

It answers four questions:

1. What ONMC is
2. What features are implemented right now
3. How the pieces fit together
4. Which workflows are intended versus out of scope

## What ONMC Is

`oh-no-my-claudecode` combines adaptive working context, repository memory,
and an execution harness for coding agents. This catalog describes code on
`main`; adaptive working context is ahead of the latest PyPI release (`v0.113.0`).

The default context path is local and deterministic. Optional model providers,
verification layers, attestations, and multi-agent adapters have separate setup
and do not all run on every invocation.

## What Is Implemented

### Adaptive working context

`onmc working enable` installs native Claude Code hooks and MCP registration.
Each session retains its goal, explicit constraints, decisions, hypotheses, and
next step. A budgeted compiler checks recalled memories against current source
contents, withdraws stale evidence, handles explicit trusted relationship edges,
and suppresses unchanged packets. Resume/compaction forces a current packet.

CLI and MCP clients can start explicit sessions, inspect context, and record
notes. Working state uses transactional local SQLite and remains separate from
Git-exported repository memory. It requires no model call. Native child-agent
working-state delivery and general semantic conflict detection are not implemented.
Instructions are advisory; source identity establishes freshness, not truth.

[Behavior, setup, and limits](working-context.md)
· [Benchmarks and live pilot](benchmarks/working-context.md)

### Canonical execution harness

`onmc run "task"` previews a typed task plan without running an agent.
`--execute` explicitly invokes a supported installed agent, configured verifier,
durable run state, and proof graph. `--isolate` binds execution to a worktree.
Policy denial, incomplete proof, or agent failure produce non-success outcomes.
Mutation verification and full adjudication are separately configured paths.

Runtime, delegation, and selective-swarm adapters exist in the codebase. Their
presence does not establish a measured advantage over a single agent. Publication
reports require independent evidence gates and currently remain blocked.

[Execution guide](harness-run.md) · [Current evidence](evidence/sota-report.md)

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

Incremental ingest is separate from working-context eligibility: the working
compiler can exclude a stale claim without deleting its durable memory record.

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
onmc brief --task "fix flaky Redis cache invalidation bug" --style compact --max-tokens 600 --stdout
onmc brief --task "fix flaky Redis cache invalidation bug" --style caveman --max-tokens 400 --stdout
onmc codegraph --max-files 25
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

For Codex and other token-sensitive agents, `--style compact` and `--style caveman` render smaller
paste-ready briefs. `--max-tokens` trims the markdown output to a hard budget, and `--stdout` avoids
terminal tables so the output can be pasted directly into an agent context.

`onmc codegraph` emits a compact directory and hot-file map from the ingested repo index. It is meant
to reduce broad file dumping by giving agents a small navigation graph before they inspect source.

### 7. Optional LLM Layer

ONMC can optionally call a configured provider:

```bash
onmc llm configure --provider anthropic --model <model-id>
onmc llm status
```

Supported providers:

- Anthropic
- OpenAI
- Ollama for a configured local server
- LiteLLM through the optional `litellm` extra
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
- `onmc hooks session-start`

What they do:

- before compaction, snapshot active task context into `compaction_snapshots`,
  enriched from the live session transcript (active files, recent assistant text)
- when the session resumes after compaction (SessionStart with source `compact`),
  compile a continuation brief and inject it into model context via the hook
  stdout contract; a debug copy lands in `.onmc/continuation-brief.md`

Hooks are installed into the project's `.claude/settings.json` (and MCP
registration into `.mcp.json`), so they travel with the repo and never fire in
unrelated projects.

### 13. MCP Server

ONMC can serve memory over MCP:

```bash
onmc serve --mcp --repo .
```

Selected tools (the agent-facing action surface):

- `start_working_context` — start an explicit session with goal and constraints
- `get_working_context` — compile/refresh that session’s current packet
- `record_working_note` — save a decision, hypothesis, or next step

- `recall` — find matching past incidents, failures, and fixes
- `search_memory` — relevance-ranked memory search by query, kind, and files
- `get_brief` — compile the task-focused brief as markdown
- `record_attempt` — record a task-scoped attempt mid-session
- `record_memory` — write a durable manual memory (never wiped by ingest)
- `list_tasks` — list task records
- `guard_task` — surface known failed approaches for a task
- `get_coverage` — report memory coverage and uncovered hotspots
- `get_digest` — summarize recent repository learning
- `get_skills` — list memory-derived reusable skills
- `get_profile` — return the local cross-repo user profile
- `ask` — answer a natural-language question from ranked repository memory

Exposed resources:

- `onmc://brief`
- `onmc://memory/list`
- `onmc://memory/{kind}`
- `onmc://memory/search?files=...`
- `onmc://tasks`
- `onmc://task/{id}`
- `onmc://snapshot/latest`
- `onmc://status`

### 14. Health Check

```bash
onmc doctor
onmc report
onmc report --output .agent-memory/readiness.md
```

The doctor command audits initialization, ingest freshness, provider setup, Claude integration,
`CLAUDE.md`, `.agent-memory/`, and post-commit hooks, and returns a nonzero exit code only for
actual errors.

The report command turns the same state into a shareable markdown artifact with readiness score,
memory/task counts, integration state, recommended next actions, and a short snippet that maintainers
can paste into PRs or handoffs.

### 15. Visual Dashboard

```bash
onmc ui
```

The read-only local dashboard exposes overview metrics, searchable memory, task state, repository
hotspots, health signals, and the shareable readiness report. It binds to `127.0.0.1:8765` by
default and uses packaged static assets with no hosted service or frontend runtime dependency.
`onmc ui --export onmc-brain.html` writes a self-contained, zero-network snapshot with embedded
data and a restrictive Content Security Policy. This gives maintainers a portable visual artifact
for demos and handoffs without introducing a hosted dashboard.

### 16. Obsidian Knowledge Vault

```bash
onmc wiki --format obsidian
```

ONMC can export stored memory as an Obsidian-native vault. Every memory becomes a note with YAML
provenance, kind and confidence metadata, subsystem links, and wikilinks for recorded relationships.
`Home.md`, `Graph.md`, and subsystem indexes make the vault usable immediately. Output defaults to
`.onmc/obsidian/`, keeping repository knowledge private unless the user explicitly chooses a shared
`--output` directory.

### 17. Accountable Autonomous Loops

```bash
onmc loop --goal "fix the failing tests" --agent claude --verify "pytest -q"
onmc loop --goal "fix the failing tests" --agent codex --verify "pytest -q"
onmc loop --goal "fix the failing tests" --agent opencode --verify "pytest -q"
```

The loop uses real headless Claude Code, Codex, or OpenCode adapters. Each iteration compiles relevant
memory, injects known failed approaches, runs the agent, executes the verifier, and records the
outcome. It stops on convergence, no progress, duplicate actions, repeated verifier errors, maximum
iterations, token budget, cost budget, or wall time. Non-dry runs write a SHA-256 hash-chained receipt
under `.agent-memory/receipts/`. Verification depends on convergence and the configured evidence requirements,
including coverage checks where required; a passing command alone is insufficient.
Default receipts are tamper-evident. Optional attestation is a separate workflow
requiring the `attest` extra; it does not prove the code is correct.

### 18. No-Mistakes PR Gate

```bash
onmc nomistakes "fix failing CI" --verify "pytest -q"
onmc nomistakes "repair the PR" --agent codex --eval-fail-under 80 --json
```

`nomistakes` composes the accountability stack into one merge-gate command: deterministic `audit`,
optional `eval` threshold, explicit autonomy level, isolated worktree execution by default,
`autopilot` KNOW→PLAN→ACT→PROVE→LEARN, hard limits, and a verified receipt. The command exits
non-zero unless all blocking gates pass and the final verifier-backed receipt is verified.

### 19. Trace, Eval, and Replay

```bash
onmc trace start --label "checkout repair"
onmc trace stop
onmc trace report
onmc eval run --fail-under 80
onmc eval compare --baseline 10
onmc replay run <trace-id> --compare
```

Trace Observatory records session events and reports memory hits, loop signals, tool outcomes, and
explicitly labelled token estimates. Eval cases deterministically test expected recall and dead-end
behavior and can gate CI. Replay re-runs recall and guard decisions over a recorded trace against the
current brain, with or without memory, without an LLM or network call.

### 20. Security and MCP Policy

```bash
onmc audit . --fail-on high
onmc mcp policy init
onmc mcp check tool-calls.jsonl --fail-on approval_required
```

`audit` statically checks agent configuration for secrets, broad permissions, risky hooks, MCP
configuration, and prompt-injection surfaces. The MCP trust gateway classifies JSONL records or stdin
as allow, block, or approval required for hook/CI enforcement. It is not a transparent network proxy
or process sandbox.

### 21. Memory-Aware GitHub Workflows

```bash
onmc gh-aw init --dry-run
onmc gh-aw init
```

The command scaffolds issue context, PR preflight, merged-PR learning, and weekly memory-audit
workflows with constrained permissions, pinned actions, and comment-only safe outputs.

### 22. Reproducible Benchmarks

```bash
onmc benchmark
onmc bench
```

`benchmark` labels live recall/compression metrics as measured and harness results as simulation.
`bench` remains a deterministic synthetic proof harness; its numbers are not presented as production
LLM measurements.

### 23. Public Python API

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
5. `sync` makes repository memory portable across machines and cloud workspaces;
   adaptive session working state remains local.
6. `working` compiles source-checked session packets through hooks and MCP;
   legacy continuation snapshots remain a separate compatibility path.
7. `serve --mcp` exposes the same state to MCP-compatible agents mid-session.
8. `run` compiles and executes the canonical contract; `loop` is the underlying
   single-agent memory/verifier execution path.
9. `nomistakes` wraps loop/autopilot with preflight gates and receipt-based approval.
10. `trace`, `eval`, and `replay` make memory contribution inspectable and regression-testable.
11. `import onmc` exposes the same capabilities programmatically.

## Current Boundaries

Important boundaries:

- each loop targets one selected agent; separate runtime/swarm adapters have their own contracts
- loop adapters depend on installed, authenticated agent CLIs
- default receipts are hash-chained; optional attestation requires separate dependencies and setup
- MCP policy classifies recorded/stdin calls; it is not an inline transport proxy or sandbox
- no hosted sync or remote collaboration
- no hosted dashboard or account system
- token/cost data is only recorded when the selected agent CLI exposes it

## Recommended Mental Model

Use ONMC as:

- a repo memory database
- a task memory ledger
- a deterministic brief compiler
- a bounded autonomous execution loop for Claude Code and Codex
- a proof and regression layer for agent memory and run outcomes
- an optional LLM reasoning layer on top of stored memory
- a continuity layer for compaction and fresh clones

Do not treat it as:

- a replacement for your coding agent
- a cloud control plane
- a guarantee that multi-agent execution improves task success
- a correctness guarantee derived from a signature or receipt

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

For bounded autonomous work:

```bash
onmc loop --goal "..." --agent claude --verify "pytest -q" --dry-run
onmc loop --goal "..." --agent claude --verify "pytest -q" --max-cost-usd 2
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
