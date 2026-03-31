# oh-no-my-claudecode

`oh-no-my-claudecode` helps coding agents and engineers recover the high-signal, repo-specific context that static instructions and raw transcripts miss.

It is a memory-first, provenance-driven CLI that scans a local git repository, stores structured repo memory in `.onmc/`, and compiles compact task briefs for coding agents such as Claude Code, Codex, or similar tools.

P0 is intentionally conservative:

- no hosted service
- no vector database
- no mandatory LLM dependency
- no autonomous coding claims

The goal is better repo context recovery, not magic.

## Problem

Coding agents repeatedly lose repo-specific context:

- they forget documented decisions and invariants
- they revisit already-known hotspots
- they miss repo-specific validation patterns
- they overfit to static instructions that are too broad or stale

`onmc` addresses that by building a local memory layer from repo docs, git history, and file structure, then using it to compile a task-specific brief before an agent starts editing.

## Product Thesis

`oh-no-my-claudecode` is a repo-native memory and context compiler.

It:

- scans a local git repository
- extracts typed structured memory with provenance
- stores that memory locally in `.onmc/memory.db`
- stores durable task lifecycle records for active engineering work
- stores task-scoped attempt logs, including failed or partial approaches
- stores task-derived memory artifacts that preserve what worked, what did not, and what conflicted with design constraints
- compiles concise task briefs for coding agents
- stays useful without paid model access

## Features

- `onmc init` bootstraps `.onmc/` state for the current repository.
- `onmc ingest` indexes repo docs, file tree metadata, git history, hotspots, and validation hints.
- `onmc task ...` tracks task-scoped engineering memory with status, branch, labels, and final summaries.
- `onmc attempt ...` records what was tried during a task, including evidence and touched files.
- `onmc memory add ...` captures durable task-derived artifacts such as fixes, failed approaches, and design conflicts.
- `onmc sync ...` exports repo memory to `.agent-memory/`, restores it on fresh machines, and can install a post-commit export hook.
- `onmc hooks ...` installs Claude Code pre/post-compaction hooks and compiles a continuation brief after compaction.
- `onmc serve --mcp` exposes ONMC state as a read-only MCP server for on-demand context pulls mid-session.
- `onmc ingest --files ...` and `onmc ingest --install-hook` support lightweight incremental ingest after commits.
- `onmc llm ...` configures optional Anthropic or OpenAI provider settings without requiring secrets in config files.
- `onmc solve`, `onmc review`, and `onmc teach` execute optional LLM-backed modes against ONMC's deterministic memory spine.
- `onmc memory list` and `onmc memory show` inspect stored memory with provenance.
- `onmc brief --task "..."` produces a compact markdown brief and pretty terminal output.
- `onmc status` reports repo root, ingest state, storage location, and config summary.
- `import onmc` exposes the same repo, memory, task, hook, and sync operations as a typed Python API.

## Agent Modes

ONMC now has the first prompt-compiler layer for three agent modes:

- `solve`: propose the next best engineering approach using repo brief, memory, failed attempts, and validation guidance
- `review`: critique a proposed approach for assumptions, regressions, and missing checks
- `teach`: explain the problem and solution shape in a staff-engineer-like way, including false leads and durable lessons

These modes do not yet run an agent loop. ONMC compiles structured prompts so a configured provider or external coding agent can reason over the repo-aware memory spine.

### Supported P0 Memory Kinds

- `doc_fact`
- `decision`
- `invariant`
- `hotspot`
- `git_pattern`
- `validation_rule`

## Installation

Python 3.11+ is required.

```bash
pip install oh-no-my-claudecode
```

For local development:

```bash
git clone <your-fork-or-repo-url>
cd oh-no-my-claudecode
pip install -e ".[dev]"
```

## Quickstart

Inside any git repository:

```bash
onmc init
onmc ingest
onmc sync --restore
onmc task start --title "Fix flaky Redis cache invalidation bug" --description "Investigate test churn around cache invalidation" --label bug
onmc attempt add task-abc123def4 --summary "Try a narrower cache fix first" --kind fix_attempt --status tried --file src/cache.py
onmc memory add task-abc123def4 --type did_not_work --title "Cache-only patch missed the worker path" --summary "Tried a narrower change in src/cache.py only"
onmc brief --task "fix flaky Redis cache invalidation bug"
onmc hooks install
onmc serve --mcp
onmc llm configure --provider anthropic --model claude-3-7-sonnet-20250219
onmc solve --task "fix flaky Redis cache invalidation bug" --task-id task-abc123def4
```

This creates local state under:

```text
.onmc/
├── compiled/
├── config.yaml
├── logs/
└── memory.db
```

## Command Examples

```bash
onmc --help
onmc init
onmc ingest
onmc ingest --files README.md docs/architecture.md
onmc ingest --install-hook
onmc sync --commit
onmc sync --restore
onmc hooks install
onmc hooks status
onmc hooks pre-compact
onmc hooks post-compact
onmc serve --mcp
onmc task start --title "Fix flaky Redis cache invalidation bug" --description "Investigate cache invalidation flow"
onmc task list
onmc task show task-abc123def4
onmc attempt add task-abc123def4 --summary "Try a cache-only fix" --kind fix_attempt --status tried
onmc attempt list task-abc123def4
onmc attempt show attempt-abc123def4
onmc attempt update attempt-abc123def4 --status rejected --evidence-against "Did not address the failing path"
onmc task status task-abc123def4 --status blocked
onmc task end task-abc123def4 --status solved --summary "Fixed cache churn and updated tests"
onmc brief --task "fix flaky Redis cache invalidation bug"
onmc memory list
onmc memory add task-abc123def4 --type fix --title "Route worker refresh through the cache boundary" --summary "The shared cache boundary fixed the flaky path"
onmc memory list --type did_not_work
onmc memory list --kind hotspot
onmc memory show artifact-123abc
onmc memory show hotspot-123abc
onmc llm status
onmc llm configure --provider anthropic --model claude-3-7-sonnet-20250219
onmc solve --task "fix flaky Redis cache invalidation bug" --task-id task-abc123def4
onmc review --task "review the proposed cache invalidation fix" --input-file notes.md
onmc teach --task "explain the cache invalidation bug" --task-id task-abc123def4
onmc status
```

## Python API

The CLI now sits on top of a small public API:

```python
import onmc

repo = onmc.init(".")
repo.ingest()
brief = repo.brief(task="fix the cache invalidation bug")
print(brief.markdown)
memories = repo.memory.search(files=["src/cache.py"])
task = repo.task.start(title="Fix cache bug", description="Track the flaky path.")
repo.sync.commit()
```

## Example Brief Output

See [examples/brief-example.md](examples/brief-example.md) for a representative artifact written by `onmc brief`.

## How It Works

### Ingest

P0 ingests:

- git commit history
- repository file tree metadata
- markdown docs such as `README*`, `docs/**/*.md`, `AGENTS.md`, `CLAUDE.md`, and architecture docs

Heuristics are deterministic and lightweight:

- docs are split into markdown sections and classified conservatively
- git history is used for hotspots, co-change patterns, and test-coupling hints
- repo shape is used to infer likely validation commands and source/test layout

### Brief Compilation

Given a task string, `onmc brief` ranks:

- relevant memory entries
- likely impacted files
- hotspot areas
- likely validation steps
- next files to inspect

The output is written to `.onmc/compiled/<timestamp>-brief.md`.

### Git-Portable Memory

`onmc sync --commit` exports repo memory, tasks, attempts, artifacts, and the most recent brief to `.agent-memory/` as stable JSON plus markdown. `onmc sync --restore` restores that state into `.onmc/memory.db` on another machine or cloud workspace.

### Hooks and Continuation Briefs

`onmc hooks install` merges Claude Code PreCompact and PostCompact hooks into `~/.claude/settings.json`. Pre-compaction stores a `CompactionSnapshot`; post-compaction compiles a continuation brief to `~/.onmc-continuation-brief.md` so the next turn can recover the active task, decisions, working hypothesis, and next step.

### MCP Server

`onmc serve --mcp` runs a read-only MCP server over stdio. It exposes:

- `onmc://brief`
- `onmc://memory/list`
- `onmc://memory/{kind}`
- `onmc://memory/search?files=...`
- `onmc://tasks`
- `onmc://task/{id}`
- `onmc://snapshot/latest`
- `onmc://status`

### Optional LLM-Backed Modes

When an optional provider is configured, ONMC can execute three end-to-end modes:

- `onmc solve`: compile the deterministic brief plus task memory, then ask the model for the next best approach
- `onmc review`: critique a proposed fix or plan, optionally with external notes from `--input-file`
- `onmc teach`: turn the same memory spine into a staff-style reasoning and learning artifact

These commands still follow the ONMC design: memory and provenance are compiled first, model reasoning happens second, and outputs are stored locally under `.onmc/compiled/`. Task-linked runs are also persisted in SQLite so they remain visible from `onmc task show`.

## Architecture Overview

High-level modules:

- `models/`: typed config, memory, ingest, and brief models
- `storage/`: local SQLite-backed state
- `task lifecycle`: durable task records stored alongside repo memory
- `attempt logging`: task-linked records of tried, rejected, partial, or successful approaches
- `memory artifacts`: durable task-derived findings that preserve fixes, failures, conflicts, gotchas, invariants, and validation guidance
- `sync/`: git-portable export/import to `.agent-memory/`
- `hooks/`: Claude Code compaction snapshots and continuation brief generation
- `mcp_server/`: read-only MCP resource handlers over stdio
- `api.py`: typed import surface for repo, memory, task, hook, and sync workflows
- `ingest/`: doc parsing, git parsing, repo scanning, and heuristic extraction
- `brief/`: task-to-context compilation and ranking
- `core/`: repo discovery and service orchestration
- `rendering/`: Rich terminal presentation

More detail:

- [docs/architecture.md](docs/architecture.md)
- [docs/memory-model.md](docs/memory-model.md)
- [docs/prompt-compiler.md](docs/prompt-compiler.md)
- [docs/shipped-capabilities.md](docs/shipped-capabilities.md)
- [docs/task-lifecycle.md](docs/task-lifecycle.md)
- [docs/roadmap.md](docs/roadmap.md)

## Limitations

- P0 does not capture chat transcripts or editor state.
- Memory extraction is heuristic and intentionally conservative.
- Task lifecycle is local-only and intentionally lightweight.
- Attempt logging is structured but intentionally manual in P0.
- Task-derived memory artifacts are manually authored in P0 rather than auto-summarized.
- Brief ranking is token-based, not embedding-based.
- Git-derived patterns are suggestions, not guarantees.
- MCP is read-only in this release; there are no write tools yet.
- LLM-backed solve/review/teach commands are explicit and single-shot; there is still no autonomous loop or tool orchestration.

## Roadmap

Short-term roadmap items live in [docs/roadmap.md](docs/roadmap.md). Near-term extensions include:

- manual memory authoring and curation
- incremental ingest and richer stale-memory handling
- optional LLM summarization behind a disabled-by-default interface
- deeper diff-aware briefing for active branches
- richer task-memory capture tied to briefs and outcomes
- linking briefs and outcomes back to recorded attempts
- artifact-assisted brief compilation that can surface prior failed approaches before a task starts

## Development

Install dev dependencies and run the full local check suite:

```bash
pip install -e ".[dev]"
ruff check .
mypy src
pytest
```

Optional pre-commit hooks:

```bash
pre-commit install
```

## Optional LLM Providers

The core ONMC workflow stays useful without a model API. The LLM layer is optional and currently limited to provider configuration, prompt compilation, and single-shot `solve` / `review` / `teach` generation.

Supported providers today:

- `anthropic`
- `openai`

Configure one locally:

```bash
onmc llm configure --provider anthropic --model claude-3-7-sonnet-20250219
export ANTHROPIC_API_KEY=...
onmc llm status
```

If Anthropic returns `model not found`, the configured model ID is stale or unavailable to your key. Run:

```bash
curl https://api.anthropic.com/v1/models \
  --header "x-api-key: $ANTHROPIC_API_KEY" \
  --header "anthropic-version: 2023-06-01"
```

Then re-run `onmc llm configure --model ...` with one of the returned IDs.

Secrets are always read from environment variables. ONMC stores the provider name, model, and API key env var name in `.onmc/config.yaml`, but it does not write the secret value itself.

Prompt compilation stays separate from provider calls. ONMC first builds a structured prompt from:

- the task record
- the deterministic repo brief
- relevant repo memory
- prior attempts
- negative memory such as `did_not_work` and `design_conflict`
- validation guidance and provenance

Then the configured provider is asked for structured JSON output, and ONMC stores the rendered result under `.onmc/compiled/` plus a task-linked output record when `--task-id` is provided.

Example:

```bash
onmc llm configure --provider anthropic --model claude-3-7-sonnet-20250219
export ANTHROPIC_API_KEY=...
onmc solve --task "fix flaky Redis cache invalidation bug" --task-id task-abc123def4
onmc review --task "review the proposed cache fix" --input-file plan.md
onmc teach --task "teach the cache invalidation reasoning" --task-id task-abc123def4
```

That keeps the memory/context layer inspectable before any model is asked to reason.

## Publishing

The repo includes:

- build metadata in `pyproject.toml`
- GitHub Actions CI
- a PyPI trusted-publishing workflow scaffold

Publishing still requires:

- a real GitHub repository
- PyPI project setup
- trusted publishing configured on the PyPI side for the GitHub `pypi` environment used by the release workflow

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
