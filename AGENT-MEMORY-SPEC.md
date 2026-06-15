# Agent Memory Format Specification

**Version:** 1  
**Status:** Open Standard  
**Reference Implementation:** [oh-no-my-claudecode (onmc)](https://github.com/oh-no-my-claudecode/onmc)  
**License:** MIT (same as the reference implementation)

---

## Introduction

`.agent-memory/` is a **git-portable, provenance-tracked, cross-agent memory format**.
It captures structured knowledge extracted from a software repository — decisions,
invariants, failure patterns, and task history — so that any AI coding agent can
read from and write to a shared knowledge base across sessions, machines, and tools.

### Why a shared format?

Agents lose context on every session boundary. Without a persistent store, the same
mistakes are repeated, known constraints are re-discovered, and hard-won decisions
evaporate. When multiple agents work in the same repository (Claude Code, Codex,
Cursor, onmc, custom orchestrators) each agent's private memory creates silos.

A **single `.agent-memory/` directory committed to the repo** solves this:

- **Git-portable** — the directory travels with the repo. Clone → instant context.
- **Provenance-tracked** — every record carries `source_type`, `source_ref`, and
  `confidence` so consumers know how trustworthy each entry is.
- **Cross-agent** — any conformant reader or writer can interoperate; no lock-in.
- **Human-readable** — plain JSON files; a human can audit, edit, or merge them.

---

## Directory Layout

```
.agent-memory/
├── manifest.json                          # Required. Format header and summary counts.
├── memories/
│   └── <kind>/
│       └── <memory-id>.json               # One file per memory entry, grouped by kind.
├── tasks/
│   └── <task-id>.json                     # One file per task bundle (task + attempts + artifacts).
└── compiled/
    └── latest-brief.md                    # Optional. Latest compiled context brief.
```

### Path rules

- `<kind>` — the `MemoryKind` enum value of the memory entry (e.g. `decision`, `invariant`).
- `<memory-id>` — the stable unique identifier of the memory entry (e.g. `decision-a3f7c1`).
- `<task-id>` — the stable unique identifier of the task (e.g. `task-b8e2d9`).
- File names use the record's `id` field directly: `<id>.json`.
- All JSON files are encoded UTF-8, pretty-printed with 2-space indent, keys sorted
  alphabetically, and end with a trailing newline.

---

## Schemas

### 1. `manifest.json`

The root index. Written by the exporter; validated first by any reader.

```json
{
  "version": "1",
  "repo_root": ".",
  "exported_at": "2026-06-15T19:49:00.058748Z",
  "onmc_version": "0.7.0",
  "counts": {
    "memories": 3,
    "tasks": 1,
    "attempts": 2,
    "artifacts": 1
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `version` | `string` | Yes | Format version. Currently `"1"`. |
| `repo_root` | `string` | Yes | Relative path from `.agent-memory/` to the repo root. Always `"."` in the reference implementation. |
| `exported_at` | `string` (ISO 8601 UTC) | Yes | Timestamp of this export run. |
| `onmc_version` | `string` | Yes | Semver of the tool that produced this export. |
| `counts.memories` | `integer` | Yes | Total memory files in `memories/`. |
| `counts.tasks` | `integer` | Yes | Total task files in `tasks/`. |
| `counts.attempts` | `integer` | Yes | Total attempt records across all task files. |
| `counts.artifacts` | `integer` | Yes | Total artifact records across all task files. |

**Forward-compatibility rule:** readers MUST ignore unknown top-level fields.

---

### 2. `memories/<kind>/<id>.json` — Memory Record

Each file contains a single top-level object with one key `"memory"`.

```json
{
  "memory": {
    "id": "decision-a3f7c1b2e4d8",
    "kind": "decision",
    "title": "Use shared cache boundary",
    "summary": "Worker code must not duplicate cache invalidation logic.",
    "details": "Observed in docs/architecture.md: all cache invalidation must go through the shared boundary to avoid divergence.",
    "source_type": "doc",
    "source_ref": "docs/architecture.md",
    "tags": ["cache", "architecture"],
    "confidence": 0.85,
    "feedback_score": 0.0,
    "created_at": "2026-06-15T10:00:00Z",
    "updated_at": "2026-06-15T12:30:00Z",
    "staleness": "fresh",
    "last_verified_at": "2026-06-15T12:30:00Z"
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | `string` | Yes | Stable unique identifier. Format: `<kind>-<hex>`. |
| `kind` | `MemoryKind` enum | Yes | Category of the memory entry. See enum values below. |
| `title` | `string` | Yes | Short human-readable title (≤ 100 chars). |
| `summary` | `string` | Yes | One-sentence distillation of the entry. |
| `details` | `string` | Yes | Full description with context and evidence. |
| `source_type` | `SourceType` enum | Yes | How this entry was produced. See enum values below. |
| `source_ref` | `string` | Yes | Provenance pointer (file path, commit hash, URL, or `"manual"`). |
| `tags` | `array[string]` | Yes (may be empty) | Free-form labels for filtering. |
| `confidence` | `float` [0.0, 1.0] | Yes | Extracted confidence from 0 (uncertain) to 1 (certain). |
| `feedback_score` | `float` | Yes | Cumulative human feedback signal. Positive = confirmed useful, negative = rejected. Default `0.0`. |
| `created_at` | `string` (ISO 8601 UTC) | Yes | Creation timestamp. |
| `updated_at` | `string` (ISO 8601 UTC) | Yes | Last modification timestamp. |
| `staleness` | `StalenessLabel` or `null` | Yes | Last computed staleness label. `null` if never verified. |
| `last_verified_at` | `string` (ISO 8601 UTC) or `null` | Yes | When staleness was last re-checked. |

#### `MemoryKind` enum values

| Value | Meaning |
|---|---|
| `doc_fact` | A fact extracted from documentation or README files. |
| `decision` | An architectural or design decision with rationale. |
| `invariant` | A constraint that must always hold (e.g. "never bypass the cache boundary"). |
| `hotspot` | A frequently-changed file or module (churn metric). |
| `git_pattern` | A pattern discovered from commit history (e.g. common co-change pairs). |
| `validation_rule` | A validation constraint (e.g. "field X must match regex Y"). |
| `failed_approach` | A recorded dead-end: an approach that was tried and did not work. |
| `design_conflict` | A tension between two design goals or between documented intent and implementation. |
| `gotcha` | A non-obvious trap or footgun that future agents should avoid. |

#### `SourceType` enum values

| Value | Meaning |
|---|---|
| `git` | Extracted from git history (commits, diffs, blame). |
| `doc` | Extracted from documentation files (README, architecture docs). |
| `code` | Extracted from source code structure or comments. |
| `manual` | Written directly by a human. |
| `manual_seed` | Seeded by a human during initial setup. |
| `llm_extracted` | Extracted by an LLM from repository content. |
| `transcript` | Mined from an agent session transcript. |
| `github_pr` | Mined from GitHub pull request reviews or comments. |

#### `StalenessLabel` values

| Value | Meaning |
|---|---|
| `fresh` | The anchor file exists and content matches. |
| `stale` | The anchor file exists but content has diverged. |
| `orphaned` | The anchor file no longer exists in the repository. |
| `unanchored` | No file anchor; staleness cannot be checked (e.g. `source_ref` is a commit hash). |

---

### 3. `tasks/<task-id>.json` — Task Bundle

Each file contains a task record, its attempt history, and its memory artifacts.

```json
{
  "task": {
    "task_id": "task-b8e2d9f1a0",
    "title": "Fix import resolution bug",
    "description": "Track and resolve the import resolution issue in src/loader.py.",
    "status": "solved",
    "created_at": "2026-06-15T09:00:00Z",
    "started_at": "2026-06-15T09:01:00Z",
    "ended_at": "2026-06-15T11:45:00Z",
    "repo_root": "/home/user/myproject",
    "branch": "fix/import-resolution",
    "labels": ["bug", "imports"],
    "final_summary": "Added sys.path entry in the entry module.",
    "final_outcome": "All tests pass. Import chain is now deterministic.",
    "confidence": 0.95
  },
  "attempts": [
    {
      "attempt_id": "attempt-3298ebd771",
      "task_id": "task-b8e2d9f1a0",
      "summary": "Try monkey-patching sys.modules",
      "kind": "fix_attempt",
      "status": "rejected",
      "reasoning_summary": "Common approach for import isolation.",
      "evidence_for": "Works in unit tests.",
      "evidence_against": "Breaks integration tests when run in parallel.",
      "files_touched": ["src/loader.py", "tests/conftest.py"],
      "created_at": "2026-06-15T09:05:00Z",
      "closed_at": "2026-06-15T10:00:00Z"
    }
  ],
  "artifacts": [
    {
      "memory_id": "artifact-014b701891",
      "task_id": "task-b8e2d9f1a0",
      "type": "fix",
      "title": "Import fix via sys.path entry",
      "summary": "Fixed by appending the src/ directory to sys.path in __main__.py.",
      "why_it_matters": "Prevents future import failures when the module is run directly.",
      "apply_when": "The entry module is invoked directly (not via the installed package).",
      "avoid_when": null,
      "evidence": "All 47 tests pass after the change.",
      "related_files": ["src/__main__.py"],
      "related_modules": ["loader"],
      "confidence": 0.9,
      "created_at": "2026-06-15T11:30:00Z"
    }
  ]
}
```

#### Task object

| Field | Type | Required | Description |
|---|---|---|---|
| `task_id` | `string` | Yes | Stable unique identifier. Format: `task-<hex>`. |
| `title` | `string` | Yes | Short task title. |
| `description` | `string` | Yes | Full task description. |
| `status` | `TaskStatus` enum | Yes | Current lifecycle status. |
| `created_at` | `string` (ISO 8601 UTC) | Yes | When the task was created. |
| `started_at` | `string` (ISO 8601 UTC) or `null` | Yes | When the task became active. |
| `ended_at` | `string` (ISO 8601 UTC) or `null` | Yes | When the task reached a terminal status. |
| `repo_root` | `string` | Yes | Absolute path to the repository root (machine-local). |
| `branch` | `string` | Yes | Git branch name when the task was created. |
| `labels` | `array[string]` | Yes (may be empty) | Free-form labels. |
| `final_summary` | `string` or `null` | Yes | Summary written at task closure. |
| `final_outcome` | `string` or `null` | Yes | Outcome description written at task closure. |
| `confidence` | `float` [0.0, 1.0] or `null` | Yes | Agent's confidence in the outcome. |

**`TaskStatus` enum values:** `open`, `active`, `blocked`, `solved`, `abandoned`

#### Attempt object

| Field | Type | Required | Description |
|---|---|---|---|
| `attempt_id` | `string` | Yes | Stable unique identifier. Format: `attempt-<hex>`. |
| `task_id` | `string` | Yes | Foreign key to the parent task. |
| `summary` | `string` | Yes | What was tried. |
| `kind` | `AttemptKind` enum | Yes | Category of the attempt. |
| `status` | `AttemptStatus` enum | Yes | Outcome of the attempt. |
| `reasoning_summary` | `string` or `null` | Yes | Why this attempt was worth trying. |
| `evidence_for` | `string` or `null` | Yes | Signals supporting the approach. |
| `evidence_against` | `string` or `null` | Yes | Signals against the approach. |
| `files_touched` | `array[string]` | Yes (may be empty) | Files modified during this attempt. |
| `created_at` | `string` (ISO 8601 UTC) | Yes | When the attempt was recorded. |
| `closed_at` | `string` (ISO 8601 UTC) or `null` | Yes | When the attempt reached a terminal status. |

**`AttemptKind` enum values:** `fix_attempt`, `investigation`, `test_strategy`, `refactor_attempt`, `other`

**`AttemptStatus` enum values:** `proposed`, `tried`, `rejected`, `succeeded`, `partial`

#### Artifact (MemoryArtifact) object

| Field | Type | Required | Description |
|---|---|---|---|
| `memory_id` | `string` | Yes | Stable unique identifier. Format: `artifact-<hex>`. |
| `task_id` | `string` | Yes | Foreign key to the parent task. |
| `type` | `MemoryArtifactType` enum | Yes | Category of the artifact. |
| `title` | `string` | Yes | Short artifact title. |
| `summary` | `string` | Yes | What worked, failed, or conflicted. |
| `why_it_matters` | `string` | Yes | Why a future agent should know this. |
| `apply_when` | `string` or `null` | Yes | When to apply this guidance. |
| `avoid_when` | `string` or `null` | Yes | When NOT to apply this guidance. |
| `evidence` | `string` | Yes | Supporting evidence from the task. |
| `related_files` | `array[string]` | Yes (may be empty) | Related repository file paths. |
| `related_modules` | `array[string]` | Yes (may be empty) | Related module or package names. |
| `confidence` | `float` [0.0, 1.0] | Yes | Confidence in this artifact's usefulness. |
| `created_at` | `string` (ISO 8601 UTC) | Yes | When the artifact was recorded. |

**`MemoryArtifactType` enum values:** `fix`, `did_not_work`, `design_conflict`, `gotcha`, `invariant`, `validation`

---

### 4. `compiled/latest-brief.md` — Compiled Brief (Optional)

A markdown document containing the most recently compiled context brief. Written by
`onmc brief` and copied during `onmc sync --commit`. This file is informational and
not validated by conformance checks.

---

## Identity and Deduplication

Every record has a **stable deterministic `id`** derived from the content at creation
time (typically a short hex digest of key fields). The id format follows:

- Memory entries: `<kind_value>-<12 hex chars>` (e.g. `decision-a3f7c1b2e4d8`)
- Tasks: `task-<10 hex chars>` (e.g. `task-b8e2d9f1a0`)
- Attempts: `attempt-<10 hex chars>` (e.g. `attempt-3298ebd771`)
- Artifacts: `artifact-<10 hex chars>` (e.g. `artifact-014b701891`)

**Deduplication rule:** when restoring, a record with an existing `id` MUST be
upserted (update-or-insert), not duplicated. The `id` is the conflict key.

---

## Provenance

Each memory entry carries:

- **`source_type`** — how it was produced (see `SourceType` enum).
- **`source_ref`** — a pointer back to the original evidence: a relative file path
  (`docs/architecture.md`), a git commit hash, a GitHub PR URL, or `"manual"` /
  `"repo_tree"` for synthetic entries.
- **`confidence`** — a float in [0, 1] indicating extraction confidence. Human-written
  entries typically start at 1.0; LLM-extracted entries are calibrated by the extractor
  (commonly 0.6–0.9).

---

## Confidence and Feedback Semantics

- **`confidence`** (memory entries and artifacts): extraction confidence. Ranges from
  0.0 (very uncertain) to 1.0 (certain). Used by readers to rank or filter entries.
- **`feedback_score`** (memory entries only): cumulative human feedback. Starts at
  `0.0`. Each confirmation increments it; each rejection decrements it. Readers MAY
  treat entries with negative feedback scores as lower priority.

---

## Staleness Semantics

The `staleness` field on memory entries reflects the last computed relationship
between the entry's `source_ref` and the current repository state:

- `null` — never checked; treat as unknown.
- `fresh` — the anchor source still matches; entry is likely accurate.
- `stale` — the anchor source has changed; entry may be outdated.
- `orphaned` — the anchor source (file) no longer exists; entry may be invalid.
- `unanchored` — no checkable anchor (e.g. source is a commit hash); cannot assess.

Staleness is computed on demand by `onmc memory verify` and stored in the database.
It is exported in the JSON snapshot as an informational field. Readers SHOULD surface
stale or orphaned entries as lower-priority but MUST NOT silently discard them.

---

## Versioning

The manifest `version` field identifies the format generation. This document describes
**version `"1"`**.

### Forward-compatibility rules (readers MUST follow)

1. **Ignore unknown fields** — if a future writer adds a new optional field to any
   record, conformant readers silently skip it.
2. **Preserve on round-trip** — if a reader re-exports a memory it read, it MUST
   include all fields it does not understand verbatim (pass-through semantics).
3. **Reject unknown versions** — if `manifest.version` is not a version the reader
   understands, it SHOULD refuse to load the directory and report the version mismatch
   clearly. Readers MAY support a subset of older versions if they document which ones.

### Planned future versions

When breaking changes are required, the `version` field will increment to `"2"`, etc.
A non-breaking additive change (new optional field) does NOT require a version bump.

---

## Conformance

### Minimal conformant reader

A reader MUST:

1. Parse `manifest.json` and validate that `version` is supported.
2. Read each `memories/<kind>/<id>.json` file; parse the `memory` object.
3. Validate that required fields are present and `kind`, `source_type`, `staleness`
   values are within their defined enum sets.
4. Read each `tasks/<task-id>.json` file; parse `task`, `attempts`, and `artifacts`.
5. Validate enum fields (`status`, `kind`, etc.) within their defined sets.
6. Ignore unknown fields (forward-compatibility).

### Minimal conformant writer

A writer MUST:

1. Write `manifest.json` with all required fields and accurate counts.
2. Write each memory file at `memories/<kind>/<memory-id>.json` with all required
   fields; use the record's `kind` value for the subdirectory.
3. Write each task bundle at `tasks/<task-id>.json` including the task, all attempts,
   and all artifacts for that task.
4. Use UTF-8 encoding, pretty-print JSON with 2-space indentation, sort keys
   alphabetically, and end each file with a newline.
5. Use deterministic, stable ids (same logical record → same id across exports).

### Reference implementation

`onmc` (oh-no-my-claudecode) is the reference implementation. Running
`onmc sync --commit` in an initialized repository produces a conformant
`.agent-memory/` directory. Running `onmc spec validate` checks conformance of any
`.agent-memory/` directory.

---

## Example: complete `.agent-memory/` tree

```
.agent-memory/
├── manifest.json
├── memories/
│   ├── decision/
│   │   └── decision-a3f7c1b2e4d8.json
│   ├── invariant/
│   │   └── invariant-9b2e44f1c7a0.json
│   └── doc_fact/
│       └── doc_fact-d4474852d160.json
├── tasks/
│   └── task-b8e2d9f1a0.json
└── compiled/
    └── latest-brief.md
```
