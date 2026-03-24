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
- compiles concise task briefs for coding agents
- stays useful without paid model access

## Features

- `onmc init` bootstraps `.onmc/` state for the current repository.
- `onmc ingest` indexes repo docs, file tree metadata, git history, hotspots, and validation hints.
- `onmc task ...` tracks task-scoped engineering memory with status, branch, labels, and final summaries.
- `onmc attempt ...` records what was tried during a task, including evidence and touched files.
- `onmc brief --task "..."` produces a compact markdown brief and pretty terminal output.
- `onmc memory list` and `onmc memory show` inspect stored memory with provenance.
- `onmc status` reports repo root, ingest state, storage location, and config summary.

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
onmc task start --title "Fix flaky Redis cache invalidation bug" --description "Investigate test churn around cache invalidation" --label bug
onmc attempt add task-abc123def4 --summary "Try a narrower cache fix first" --kind fix_attempt --status tried --file src/cache.py
onmc brief --task "fix flaky Redis cache invalidation bug"
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
onmc memory list --kind hotspot
onmc memory show hotspot-123abc
onmc status
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

## Architecture Overview

High-level modules:

- `models/`: typed config, memory, ingest, and brief models
- `storage/`: local SQLite-backed state
- `task lifecycle`: durable task records stored alongside repo memory
- `attempt logging`: task-linked records of tried, rejected, partial, or successful approaches
- `ingest/`: doc parsing, git parsing, repo scanning, and heuristic extraction
- `brief/`: task-to-context compilation and ranking
- `core/`: repo discovery and service orchestration
- `rendering/`: Rich terminal presentation

More detail:

- [docs/architecture.md](docs/architecture.md)
- [docs/memory-model.md](docs/memory-model.md)
- [docs/task-lifecycle.md](docs/task-lifecycle.md)
- [docs/roadmap.md](docs/roadmap.md)

## Limitations

- P0 does not capture chat transcripts or editor state.
- Memory extraction is heuristic and intentionally conservative.
- Task lifecycle is local-only and intentionally lightweight.
- Attempt logging is structured but intentionally manual in P0.
- Brief ranking is token-based, not embedding-based.
- Git-derived patterns are suggestions, not guarantees.
- Manual memory authoring is schema-ready but not yet exposed as a CLI workflow.
- Optional LLM enhancement hooks are not implemented in P0.

## Roadmap

Short-term roadmap items live in [docs/roadmap.md](docs/roadmap.md). Near-term extensions include:

- manual memory authoring and curation
- incremental ingest and richer stale-memory handling
- optional LLM summarization behind a disabled-by-default interface
- deeper diff-aware briefing for active branches
- richer task-memory capture tied to briefs and outcomes
- linking briefs and outcomes back to recorded attempts

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

## Publishing

The repo includes:

- build metadata in `pyproject.toml`
- GitHub Actions CI
- a PyPI trusted-publishing workflow scaffold

Publishing still requires:

- a real GitHub repository
- PyPI project setup
- trusted publishing configured on the PyPI side

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
