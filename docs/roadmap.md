# Roadmap

## P0

Shipped in this repo:

- installable Python package
- repo-local `.onmc/` state
- SQLite memory store
- doc ingestion
- git-history ingestion
- hotspot and git-pattern extraction
- task brief compilation
- memory inspection commands
- tests, linting, CI, and packaging scaffolding

## P1

- manual memory CRUD
- incremental ingest with stale-entry pruning by source fingerprint
- richer test-mapping heuristics
- branch-aware briefing
- memory import/export

## P2

- optional LLM summarization interface
- diff-aware ingest
- explicit ADR parsing
- configurable ranking weights
- agent-facing output presets for different coding tools

## Explicit Non-Goals

These are not planned for the MVP path:

- hosted dashboard
- remote sync
- auth
- vector database as a requirement
- generic multi-agent orchestration runtime
- autonomous patching engine

