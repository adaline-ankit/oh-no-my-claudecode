# Memory Model

P0 memory is typed structured repo knowledge, not raw chat history.

ONMC now stores two conservative memory layers:

- repo-derived memory from ingest
- task-derived memory artifacts recorded from completed or in-progress task work

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

## Task-Derived Memory Artifacts

Task-derived memory artifacts are separate from repo ingest. They preserve durable findings from task execution and attempts.

Each artifact stores:

- `memory_id`
- `task_id`
- `type`
- `title`
- `summary`
- `why_it_matters`
- `apply_when`
- `avoid_when`
- `evidence`
- `related_files`
- `related_modules`
- `confidence`
- `created_at`

These artifacts are linked back to the task that produced them. That provenance matters: ONMC should preserve not just final fixes, but also rejected or incompatible paths.

### Supported Artifact Types

#### `fix`

A working approach worth reusing.

Examples:

- route worker refresh changes through the shared cache boundary

#### `did_not_work`

A tried approach that future agents should avoid repeating.

Examples:

- narrowing the change to `src/cache.py` only, when the failure crossed into worker logic

#### `design_conflict`

A solution that conflicted with a repo constraint, invariant, or design principle.

Examples:

- bypassing a shared cache boundary that architecture docs mark as required

#### `gotcha`

A sharp edge that regularly surprises implementers.

#### `invariant`

A task-derived invariant worth preserving in future edits.

#### `validation`

A durable validation rule learned from task work.

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

Task-derived artifacts use task linkage as provenance. `memory show` makes that explicit so future agents can see:

- which task produced the artifact
- whether it was a `fix`, `did_not_work`, or `design_conflict`
- what evidence supported the record

Examples:

```bash
onmc memory add task-abc123def4 \
  --type did_not_work \
  --title "Cache-only patch missed the worker path" \
  --summary "Tried narrowing the fix to src/cache.py only." \
  --why-it-matters "Future agents should not repeat a cache-only patch for this failure mode." \
  --avoid-when "The failing path crosses worker refresh logic." \
  --evidence "The worker test still failed after the narrow change."

onmc memory add task-abc123def4 \
  --type design_conflict \
  --title "Do not bypass the shared cache boundary" \
  --summary "A direct worker-side invalidation looked simpler but violated the documented boundary." \
  --why-it-matters "This repo expects invalidation to stay centralized." \
  --evidence "docs/architecture.md explicitly states workers should not bypass the cache boundary."
```
