# AGENTS.md

This file gives Codex, cloud coding agents, and other repository-aware agents the
same maintainer expectations that Claude Code receives from `CLAUDE.md`.

## Mission

Improve ONMC as a local-first memory layer for coding agents. Keep the package narrow:
repo-native memory, provenance-aware context, Claude Code hooks, MCP resources/tools,
Codex-friendly restore flows, and portable `.agent-memory` exports.

## Required Workflow

1. Inspect the existing code path before editing.
2. Add or update tests for behavior changes.
3. Run focused validation first.
4. Run the full quality gate before publishing:

```bash
ruff check .
mypy src
pytest --cov=oh_no_my_claudecode --cov-report=term-missing --cov-fail-under=80
python scripts/generate-cli-reference.py --check
python -m build
python -m twine check dist/*
```

## Boundaries

Do not:

- commit `.onmc/`, secrets, tokens, private prompts, or proprietary source snippets
- add telemetry or hosted dependencies without maintainer approval
- bypass the LLM provider abstraction
- add a second storage backend without a design issue
- silently rewrite generated memory provenance

Do:

- keep diffs focused
- preserve user-authored sections in generated files where the code supports it
- document CLI, hook, MCP, sync, or agent-context behavior changes
- regenerate `docs/cli-reference.md` when CLI commands or help text change
- prefer deterministic behavior over opaque inference in core paths

## Pull Request Expectations

Every PR should explain:

- what changed
- why it is in scope for ONMC
- how it was validated
- whether it changes Claude Code, Codex, MCP, or `.agent-memory` behavior
