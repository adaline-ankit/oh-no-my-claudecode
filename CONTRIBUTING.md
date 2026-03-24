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
pytest
```

## Scope Guidance

This project is intentionally narrow. Good contributions should keep the tool:

- local-first
- provenance-driven
- useful without mandatory model access
- honest about heuristic confidence

Avoid turning the project into a hosted platform, a generic multi-agent wrapper, or a prompt-pack repository.

## Pull Requests

- keep changes focused
- add or update tests for behavior changes
- update docs when CLI behavior or memory semantics change
- prefer deterministic heuristics over opaque inference for core paths

## Release Notes

Release automation is scaffolded through GitHub Actions trusted publishing, but repository and PyPI configuration still need to be wired in the target GitHub project.

