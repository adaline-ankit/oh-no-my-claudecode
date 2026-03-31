# ONMC Task Brief

- Task: fix flaky Redis cache invalidation bug
- Generated: 2026-03-24T00:40:37.103968+00:00
- Repo: `/Users/ankit/Desktop/onmc`

## Task

Task focus: fix flaky Redis cache invalidation bug. Use stored repo memory plus the ranked files below to recover project-specific context quickly.

## Repo Overview

- Indexed 44 files from the current repository tree.
- Top-level areas: src, tests, docs, .gitignore, .pre-commit-config.yaml.
- Analyzed 0 git commits during the last ingest.
- Parsed 4 markdown documents.
- Detected Python validation tools: mypy, pytest, ruff.

## Most Relevant Memory

### [doc_fact] README.md: Command Examples

- Summary: ```bash onmc --help onmc init onmc ingest onmc brief --task "fix flaky Redis cache invalidation bug" onmc memory list onmc memory list --kind hotspot onmc me...
- Source: `doc:README.md`
- Confidence: 0.55

### [doc_fact] README.md: Quickstart

- Summary: Inside any git repository: ```bash onmc init onmc ingest onmc brief --task "fix flaky Redis cache invalidation bug" ``` This creates local state under: ```te...
- Source: `doc:README.md`
- Confidence: 0.55

### [invariant] memory-model.md: `invariant`

- Summary: A rule the repo expects developers to preserve. Examples: - “Do not bypass the cache boundary from workers.”
- Source: `doc:docs/memory-model.md`
- Confidence: 0.75

### [decision] memory-model.md: `decision`

- Summary: Documented architectural or workflow choices. Examples: - an architecture doc explains why a shared cache boundary exists
- Source: `doc:docs/memory-model.md`
- Confidence: 0.70

### [doc_fact] memory-model.md: `hotspot`

- Summary: Areas or files with repeated churn in git history. Examples: - `src/cache.py` changed in many commits
- Source: `doc:docs/memory-model.md`
- Confidence: 0.55

### [validation_rule] Validation tool configured: mypy

- Summary: Repository configuration indicates `mypy` is part of the local validation flow.
- Source: `code:pyproject.toml`
- Confidence: 0.85

### [validation_rule] Validation tool configured: pytest

- Summary: Repository configuration indicates `pytest` is part of the local validation flow.
- Source: `code:pyproject.toml`
- Confidence: 0.85

### [validation_rule] Validation tool configured: ruff

- Summary: Repository configuration indicates `ruff` is part of the local validation flow.
- Source: `code:pyproject.toml`
- Confidence: 0.85

## Likely Impacted Areas

- docs/memory-model.md
- pyproject.toml
- README.md
- tests/conftest.py
- tests/test_brief.py
- tests/test_cli.py

## Files To Inspect First

1. `tests/conftest.py`
1. `tests/test_brief.py`
1. `tests/test_cli.py`
1. `tests/test_ingest.py`
1. `tests/test_repo.py`
1. `tests/test_storage.py`
1. `README.md`
1. `docs/memory-model.md`
1. `pyproject.toml`

## Risk Notes

- memory-model.md: `invariant`: A rule the repo expects developers to preserve. Examples: - “Do not bypass the cache boundary from workers.”
- memory-model.md: `decision`: Documented architectural or workflow choices. Examples: - an architecture doc explains why a shared cache boundary exists

## Validation Checklist

- Run `pytest` for the affected area or the closest targeted subset.
- Run `ruff check .` before finalizing changes.
- Run `mypy src` if the task touches typed Python modules.
- Compare local validation against CI workflow hints: ci.yml, release.yml.

## Next Reading List

1. `README.md`
1. `docs/memory-model.md`
1. `pyproject.toml`
1. `tests/conftest.py`
1. `tests/test_brief.py`
1. `tests/test_cli.py`
1. `tests/test_ingest.py`
1. `tests/test_repo.py`

## Provenance

- doc_fact: doc:README.md
- invariant: doc:docs/memory-model.md
- decision: doc:docs/memory-model.md
- doc_fact: doc:docs/memory-model.md
- validation_rule: code:pyproject.toml
- Last ingest: 2026-03-24T00:40:36+00:00
