# CLAUDE.md

## Project overview
Primary source directories include .agent-memory, .agent-memory/memories, ., src/oh_no_my_claudecode, src/onmc. ```bash onmc brief --task "fix the cache invalidation bug" ```bash onmc claude-md generate # generate CLAUDE.md from memory store onmc claude-md update # refresh stale sections, preserve user-written ones onmc claude...

## Critical invariants
- Provider abstraction invariant: All LLM calls must go through the provider abstraction in llm/ — never hardcode Anthropic or OpenAI in feature code
- README.md: What it does: Your coding agent starts every session like it has never seen your codebase before. It doesn't know why the code looks the way it does, what was tried and fa...

## Architecture decisions
- README.md: Get started: ```bash pip install oh-no-my-claudecode onmc setup ``` That's it. `onmc setup` reads your git history, extracts architectural decisions and invariants, gener...
- README.md: Memory extraction: ```bash onmc ingest # scan git history, docs, source — extract structured memory onmc ingest --files x # re-ingest specific files onmc ingest --install-hook...
- prompt-compiler.md: Why Memory Is Injected This Way: ONMC is memory-first. The prompt compiler uses the deterministic brief as the spine, then adds task-scoped records around it: - repo memory provides durable...
- shipped-capabilities.md: 1. Repo Memory Ingest: ONMC can initialize local state and ingest repo knowledge with: ```bash onmc init onmc ingest ``` What gets stored: - markdown-derived facts, decisions, inva...
- shipped-capabilities.md: 2. Incremental Ingest: ONMC can reprocess only selected files: ```bash onmc ingest --files README.md docs/architecture.md ``` What this updates: - matching doc memories for those f...

## Hotspot areas
- High-risk ONMC core files: src/oh_no_my_claudecode/cli.py and src/oh_no_my_claudecode/storage/sqlite.py are dangerous to change without understanding first
- High-churn file: README.md: Observed 15 modifying commits in the last 33 analyzed commits for README.md. Recent churn count in the last 30 days: 15.
- High-churn file: src/oh_no_my_claudecode/cli.py: Observed 13 modifying commits in the last 33 analyzed commits for src/oh_no_my_claudecode/cli.py. Recent churn count in the last 30 days: 13.
- High-churn file: src/oh_no_my_claudecode/core/service.py: Observed 16 modifying commits in the last 33 analyzed commits for src/oh_no_my_claudecode/core/service.py. Recent churn count in the last 30 days: 16.
- High-churn file: src/oh_no_my_claudecode/rendering/console.py: Observed 11 modifying commits in the last 33 analyzed commits for src/oh_no_my_claudecode/rendering/console.py. Recent churn count in the last 30 days: 11.
- Hotspot subsystem: docs: docs shows repeated churn across 10 commits in the analyzed history.

## Known bad approaches
- Second database anti-pattern: Adding a second database or ORM alongside SQLite did not work — the storage layer must stay single-file SQLite

## Validation
- CI workflow hints: GitHub Actions workflows are present: ci.yml, release.yml.
- Tests often accompany .: Changes under . frequently land with tests (10 commits).
- Tests often accompany docs: Changes under docs frequently land with tests (7 commits).
- Tests often accompany src/oh_no_my_claudecode: Changes under src/oh_no_my_claudecode frequently land with tests (16 commits).
- Validation tool configured: mypy: Repository configuration indicates `mypy` is part of the local validation flow.
- Validation tool configured: pytest: Repository configuration indicates `pytest` is part of the local validation flow.

## Current active tasks
No active tasks are currently recorded.
