# Contributing

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Local Checks

```bash
ruff check .
mypy src
pytest --cov=oh_no_my_claudecode --cov-report=term-missing --cov-fail-under=80
python scripts/generate-cli-reference.py --check
python -m build
python -m twine check dist/*
```

Run the smallest relevant test while developing, then run the full gate before asking
for review.

## Scope Guidance

This project is intentionally narrow. Good contributions should keep the tool:

- local-first
- provenance-driven
- useful without mandatory model access
- honest about heuristic confidence

Avoid turning the project into a hosted platform, a generic multi-agent wrapper, or a prompt-pack repository.

Good issue areas:

- Claude Code hook reliability
- MCP resources and tools
- Codex and cloud-agent restore flows
- portable `.agent-memory` workflows
- memory provenance, ranking, and debugging
- setup, doctor, and health checks

Open a design issue before adding:

- telemetry
- a hosted service
- new long-running daemons
- a new storage backend
- a new LLM provider dependency path
- broad prompt-pack or multi-agent orchestration features

## Pull Requests

- keep changes focused
- add or update tests for behavior changes
- update docs when CLI behavior or memory semantics change
- prefer deterministic heuristics over opaque inference for core paths
- explain whether Claude Code, Codex, MCP, sync, or `.agent-memory` behavior changed
- do not commit `.onmc/`, secrets, private prompts, or proprietary source snippets
- expect maintainer review through `CODEOWNERS`
- regenerate `docs/cli-reference.md` when CLI help changes

Agent-generated PRs are welcome when they are reproducible. Include the exact commands
used for validation and keep the diff scoped to the issue.

## Labels

Maintainers use labels to route work:

- `needs-triage`: new issue or PR needs maintainer classification
- `good first issue`: narrow, documented, and safe for new contributors
- `help wanted`: maintainer wants outside implementation help
- `agent-integration`: Claude Code, Codex, Cursor, MCP, or cloud-agent path
- `memory-model`: extraction, provenance, ranking, or sync semantics
- `security`: vulnerability, secret-handling, or trust-boundary concern
- `ci`: GitHub Actions, release, packaging, or quality gate work

## Release Notes

Release automation is scaffolded through GitHub Actions trusted publishing, but repository and PyPI configuration still need to be wired in the target GitHub project.
