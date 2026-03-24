# ONMC Task Brief

- Task: fix flaky Redis cache invalidation bug
- Generated: 2026-03-24T10:12:00+00:00
- Repo: `/workspace/sample-repo`

## Task

Task focus: fix flaky Redis cache invalidation bug. Use stored repo memory plus the ranked files below to recover project-specific context quickly.

## Repo Overview

- Indexed 142 files from the current repository tree.
- Top-level areas: src, tests, docs, .github.
- Analyzed 87 git commits during the last ingest.
- Parsed 6 markdown documents.
- Detected Python validation tools: pytest, ruff, mypy.

## Most Relevant Memory

### [decision] architecture.md: Decision

- Summary: We use a shared cache boundary so worker code does not duplicate invalidation logic.
- Source: `doc:docs/architecture.md`
- Confidence: 0.75

### [hotspot] High-churn file: src/cache/redis_store.py

- Summary: Observed 14 modifying commits in the last 87 analyzed commits for src/cache/redis_store.py. Recent churn count in the last 30 days: 4.
- Source: `git:src/cache/redis_store.py`
- Confidence: 0.90

### [validation_rule] Tests often accompany src/cache

- Summary: Changes under src/cache frequently land with tests/cache (6 commits).
- Source: `git:src/cache|tests/cache`
- Confidence: 0.80

## Likely Impacted Areas

- src/cache
- tests/cache
- docs/architecture.md

## Files To Inspect First

1. `src/cache/redis_store.py`
1. `src/cache/invalidation.py`
1. `tests/cache/test_redis_store.py`
1. `docs/architecture.md`
1. `README.md`

## Risk Notes

- Hotspot subsystem: src/cache: src/cache shows repeated churn across 18 commits in the analyzed history.
- architecture.md: Decision: We use a shared cache boundary so worker code does not duplicate invalidation logic.
- src/cache/redis_store.py has elevated churn (14 modifying commits in analyzed history).

## Validation Checklist

- Run `pytest` for the affected area or the closest targeted subset.
- Run `ruff check .` before finalizing changes.
- Run `mypy src` if the task touches typed Python modules.
- Inspect or update related tests in `tests/cache/test_redis_store.py`.
- Compare local validation against CI workflow hints: ci.yml.

## Next Reading List

1. `docs/architecture.md`
1. `src/cache/redis_store.py`
1. `tests/cache/test_redis_store.py`
1. `README.md`

## Provenance

- decision: doc:docs/architecture.md
- hotspot: git:src/cache/redis_store.py
- validation_rule: git:src/cache|tests/cache
- Last ingest: 2026-03-24T10:10:00+00:00

