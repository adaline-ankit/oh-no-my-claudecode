# Memory Model

P0 memory is typed structured repo knowledge, not raw chat history.

## Schema

Each memory entry stores:

- `id`
- `kind`
- `title`
- `summary`
- `details`
- `source_type`
- `source_ref`
- `tags`
- `confidence`
- `created_at`
- `updated_at`

## Supported Kinds

### `doc_fact`

Stable repo facts extracted from markdown docs or repo shape.

Examples:

- local setup instructions from `README.md`
- primary source layout inferred from the repo tree

### `decision`

Documented architectural or workflow choices.

Examples:

- an architecture doc explains why a shared cache boundary exists

### `invariant`

A rule the repo expects developers to preserve.

Examples:

- “Do not bypass the cache boundary from workers.”

### `hotspot`

Areas or files with repeated churn in git history.

Examples:

- `src/cache.py` changed in many commits

### `git_pattern`

A repeated co-change pattern inferred from history.

Examples:

- `src/api` and `tests/api` often change together

### `validation_rule`

A validation hint from docs, repo shape, or git history.

Examples:

- the repo appears to use `pytest`
- changes in a subsystem often land with a certain test directory

## Provenance

Every memory entry is tied to a source:

- `git`
- `doc`
- `code`
- `manual`

P0 deliberately phrases git-derived memories as suggestions. They are meant to guide inspection, not to overclaim architectural truth.

