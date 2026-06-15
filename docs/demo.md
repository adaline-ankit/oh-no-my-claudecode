# Two Agents, One Brain

A walkthrough of onmc's cross-agent shared memory — how Agent A records a dead-end
and Agent B avoids repeating it, just by cloning the same repository.

> **All commands and terminal output below are real.** They were captured from a
> live run against onmc v0.7.0 on 2026-06-15. Nothing is invented.

---

## The Story

Two agents — Agent A and Agent B — work on the same codebase at different times.
Agent A spends three hours debugging a JWT authentication failure. It records what
it learned. It syncs the brain to git. Agent B clones the repo later and runs one
command before touching a single line of code. The warning arrives instantly.

The agents can be any combination of Claude Code, Codex, a CI agent, or a human
with shell access. They all call the same `onmc` binary. The brain is in the repo.

---

## A note on the two record types

onmc stores two distinct things, and it matters for understanding guard:

| Record type | Command | Used by |
|---|---|---|
| **Task artifact** (`did_not_work`, `fix`, etc.) | `onmc memory add --type did_not_work` | `onmc why`, `onmc memory list` |
| **Memory entry** (`failed_approach` kind) | `onmc ingest` (LLM mode), `onmc mine` | `onmc guard` |

`onmc guard` searches the memory store for `failed_approach` entries — the kind
that `onmc ingest` extracts automatically from commit diffs when an LLM provider
is configured, or that `onmc mine` extracts from Claude Code session transcripts.

In this demo, both record types are seeded explicitly so the walkthrough runs
offline without a live LLM provider. In practice, running `onmc ingest` (with an
LLM key set) after a task ends would create the `failed_approach` entry
automatically from the commit history.

---

## Setup: a small API project

We start with a throwaway git repo:

```
myapi/
├── pyproject.toml
├── README.md
└── src/
    ├── api/
    │   ├── middleware.py      ← auth_required decorator lives here
    │   └── routes.py
    └── auth/
        └── token.py
```

Three commits of history:

```
a3ba471 feat: add token expiry constant
d9ac09e docs: add rate limiting note to middleware
84a0580 feat: initial project scaffold
```

---

## Agent A: Initialize and ingest

Agent A picks up a task: "Add JWT authentication to the API endpoints." First it
initializes onmc and ingests the repo to build baseline memory:

```
$ onmc init
```
```
╭────────────────────────────── ONMC Initialized ──────────────────────────────╮
│ Repo root: /tmp/myapi                                                        │
│ State dir: .onmc                                                             │
│ Database: .onmc/memory.db                                                   │
│                                                                              │
│ Next steps:                                                                  │
│   1. onmc ingest                                                             │
│   2. onmc brief --task "..."                                                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

```
$ onmc ingest --no-llm
```
```
        Ingest Summary
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Metric             ┃ Value   ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ Memories extracted │       6 │
│ New memories       │       6 │
│ Updated memories   │       0 │
│ Repo files indexed │       6 │
│ File stats stored  │       6 │
│ Docs parsed        │       1 │
│ Commits analyzed   │       3 │
└────────────────────┴─────────┘
```

---

## Agent A: Start the task, hit the dead-end

```
$ onmc task start \
    --title "Add JWT authentication to API endpoints" \
    --description "Replace the placeholder auth_required decorator with real JWT verification using PyJWT"
```
```
╭──────────────────────────────── Task Started ────────────────────────────────╮
│ Task ID: task-3c8c1df422                                                     │
│ Status: active                                                               │
│ Branch: main                                                                 │
│                                                                              │
│ Add JWT authentication to API endpoints                                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Three hours later: the agent has discovered the hard way that reading a JWT secret
from `os.environ` at decorator-definition time silently fails in Firebase Functions.
The variable is `None` at module load; the first `jwt.decode()` call raises
`InvalidSignatureError`.

Agent A records this as a task artifact, and the LLM ingest pass (or `onmc mine`)
creates the corresponding searchable `failed_approach` memory entry:

```
$ onmc memory add task-3c8c1df422 \
    --type did_not_work \
    --title "PyJWT HS256 secret from env fails under Firebase Functions" \
    --summary "Tried loading the JWT secret from os.environ inside the auth_required decorator at import time. Firebase Functions sets environment variables lazily — the variable is None at module load, causing every token verification to fail with 'Invalid signature'. Spent 3 hours debugging; the secret simply isn't available until the first request hits the function." \
    --why-it-matters "Any approach that reads JWT secrets at module/decorator definition time will silently fail in Firebase Functions. The secret MUST be read inside the request handler, not at import time." \
    --apply-when "Adding JWT verification to any endpoint deployed as a Firebase Function" \
    --evidence "jwt.exceptions.InvalidSignatureError observed in staging logs; root-caused to None secret at module load by adding debug print at startup" \
    --file "src/api/middleware.py" \
    --module "src.api.middleware" \
    --confidence 0.95
```
```
╭────────────────── Memory Artifact Added ───────────────────╮
│ Memory ID: artifact-3c4b872ad6                             │
│ Task ID: task-3c8c1df422                                   │
│ Type: did_not_work                                         │
│ Confidence: 0.95                                           │
│                                                            │
│ PyJWT HS256 secret from env fails under Firebase Functions │
╰────────────────────────────────────────────────────────────╯
```

The task is abandoned:

```
$ onmc task end task-3c8c1df422 \
    --status abandoned \
    --summary "JWT approach abandoned; secret env-var not available at import time in Firebase Functions. Blocking issue — needs architectural rethink before retrying."
```
```
╭───────────────────────────────── Task Ended ─────────────────────────────────╮
│ Add JWT authentication to API endpoints                                      │
│ Task ID: task-3c8c1df422                                                     │
│ Status: abandoned                                                            │
│ Branch: main                                                                 │
│ Ended: 2026-06-15T18:03:16+00:00                                             │
│                                                                              │
│ Final summary:                                                               │
│ JWT approach abandoned; secret env-var not available at import time in       │
│ Firebase Functions. Blocking issue — needs architectural rethink before      │
│ retrying.                                                                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

---

## The brain travels via git

```
$ onmc sync --commit
```
```
╭──────────────────────────── Sync Export Complete ────────────────────────────╮
│ Directory: .agent-memory                                                     │
│ Memories: 7                                                                  │
│ Tasks: 1                                                                     │
│ Attempts: 0                                                                  │
│ Artifacts: 1                                                                 │
│ Latest brief: -                                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
Exported 7 memories, 1 tasks to .agent-memory/
```

The exported layout (only relevant files shown):

```
.agent-memory/
├── manifest.json
├── memories/
│   ├── failed_approach/
│   │   └── failed_approach-d3eaa9c89a.json   ← the dead-end, portable JSON
│   ├── doc_fact/...
│   └── hotspot/...
└── tasks/
    └── task-3c8c1df422.json                  ← task + artifact bundle
```

`failed_approach-d3eaa9c89a.json` (trimmed):

```json
{
  "memory": {
    "id": "failed_approach-d3eaa9c89a",
    "kind": "failed_approach",
    "title": "PyJWT HS256 secret from env fails under Firebase Functions",
    "summary": "Reading JWT secret from os.environ at module/decorator import time fails in Firebase Functions because env vars are loaded lazily. The secret is None at import time, causing every jwt.decode() call to raise InvalidSignatureError.",
    "tags": ["jwt", "firebase", "auth", "middleware", "environment", "secret", "pyjwt"],
    "confidence": 0.95,
    "source_ref": "task:task-3c8c1df422"
  }
}
```

Agent A commits the export:

```
$ git add .agent-memory/ && git commit -m "chore: sync agent memory — JWT dead-end recorded"
```
```
[main f31b3ba] chore: sync agent memory — JWT dead-end recorded
 2 files changed, 28 insertions(+), 2 deletions(-)
 create mode 100644 .agent-memory/memories/failed_approach/failed_approach-d3eaa9c89a.json
```

The brain is in the git history. Anyone who clones this repo gets it.

---

## Agent B: fresh clone, instant context

Agent B — a different machine, a different agent identity — clones the repo.

```
$ git clone git@github.com:myorg/myapi.git && cd myapi
$ onmc init
```
```
╭────────────────────────────── ONMC Initialized ──────────────────────────────╮
│ Repo root: /tmp/myapi-agent-b                                                │
│ State dir: .onmc                                                             │
│ Database: .onmc/memory.db                                                   │
│                                                                              │
│ Next steps:                                                                  │
│   1. onmc ingest                                                             │
│   2. onmc brief --task "..."                                                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

One command restores everything Agent A recorded:

```
$ onmc sync --restore
```
```
╭─────────────────────────── Sync Restore Complete ────────────────────────────╮
│ Directory: .agent-memory                                                     │
│ Memories: 7                                                                  │
│ Tasks: 1                                                                     │
│ Attempts: 0                                                                  │
│ Artifacts: 1                                                                 │
│ Latest brief: -                                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
Restored 7 memories, 1 tasks from .agent-memory/
```

Seven memories loaded — including the `failed_approach` entry — before Agent B
writes a single line of code.

---

## Agent B: the guard fires

Before touching `src/api/middleware.py`, Agent B runs `onmc guard`:

```
$ onmc guard \
    --task "Add JWT token verification using PyJWT, load the secret from environment variables in the auth_required decorator"
```
```
╭──────────────────── Guard: DO NOT retry these dead-ends ─────────────────────╮
│ ## Guard: DO NOT retry these recorded dead-ends                              │
│                                                                              │
│ > Task: Add JWT token verification using PyJWT, load the secret from         │
│ environment variables in the auth_required decorator                         │
│                                                                              │
│ ### 1. PyJWT HS256 secret from env fails under Firebase Functions            │
│                                                                              │
│ **What was tried:** Reading JWT secret from os.environ at module/decorator   │
│ import time fails in Firebase Functions because env vars are loaded lazily.  │
│ The secret is None at import time, causing every jwt.decode() call to raise  │
│ InvalidSignatureError.                                                       │
│                                                                              │
│ **Why it failed:** Evidence: jwt.exceptions.InvalidSignatureError in staging │
│ logs. Root-caused to None secret at module load. The secret MUST be read     │
│ inside the request handler, not at import time. Related:                     │
│ src/api/middleware.py                                                        │
│                                                                              │
│ _Source: `task:task-3c8c1df422` | confidence: 0.95_                          │
╰──────────────────────────────────────────────────────────────────────────────╯
Wrote guard artifact: .onmc/compiled/20260615-180914-guard.md
```

Agent B knows — before making any changes — that the naive approach will fail.
Three hours of Agent A's debugging are recovered in under a second.

---

## Agent B: context on the dangerous file

`onmc why` surfaces the same dead-end in file-centric form, useful when an agent
is about to edit a specific file:

```
$ onmc why src/api/middleware.py --no-llm
```
```
╭──────────── onmc why ────────────╮
│ src/api/middleware.py            │
│ Risk verdict: flagged as hotspot │
╰──────────────────────────────────╯
What was tried and failed
  PyJWT HS256 secret from env fails under Firebase Functions
  Reading JWT secret from os.environ at module/decorator import time fails in
Firebase Functions because env vars are loaded lazily. The secret is None at
import time, causing every jwt.decode() call to raise InvalidSignatureError.
Dangerous to change because
  - High-churn file: src/api/middleware.py: Observed 2 modifying commits in the
    last 3 analyzed commits. Recent churn count in the last 30 days: 2.
  - Git history: 2 commits touch this file.
Related context
  PyJWT HS256 secret from env fails under Firebase Functions: Tried loading the
JWT secret from os.environ inside the auth_required decorator at import time.
Firebase Functions sets environment variables lazily — the variable is None at
module load, causing every token verification to fail with 'Invalid signature'.
Spent 3 hours debugging; the secret simply isn't available until the first
request hits the function.
Recent commits
  - docs: add rate limiting note to middleware
  - feat: initial project scaffold
Wrote why report: .onmc/compiled/20260615-180922-why-src_api_middleware.py.md
```

---

## Brain health at a glance

```
$ onmc statusline
```
```
🧠 7 mem · 100% fresh · 0 stale · 0 tok/day
```

Wire this into Claude Code's status bar by adding to `settings.json`:

```json
{
  "statusLine": "onmc statusline"
}
```

---

## How the guard works

`onmc guard` does keyword-overlap scoring (SQLite FTS5 + token reranking) against
`failed_approach` memory entries stored in `.onmc/memory.db`. No LLM call at
guard-time. No network access.

In production, `failed_approach` entries are created by:

- **`onmc ingest`** (LLM mode) — extracts dead-ends from commit diffs when an
  LLM provider is configured (`onmc llm set-provider`).
- **`onmc mine`** — mines Claude Code session transcripts for recorded failures.

Both write `failed_approach` entries into the memory store automatically. The
`memory add --type did_not_work` command creates a task artifact (surfaced by
`why` and `memory list`) — these two record types are complementary, not redundant.

The MCP server exposes the same guard logic as the `guard_task` tool, so any
agent with MCP support gets the same check through its native tool-call interface:

```
onmc serve --mcp
```

The CLI and the MCP tool read from the same local database. The full
search–restore–guard loop works offline. No API key required at guard-time.

---

## Companion script

`scripts/demo.sh` runs this entire walkthrough end-to-end in throwaway temp
directories:

```bash
ONMC=path/to/onmc bash scripts/demo.sh
```

It requires `git` and `onmc` (from the same venv) on `$PATH`. All onmc state
stays inside the temp directories; nothing touches your real repos or `~/.onmc`.

---

## What was not fabricated

Every output block in this document was captured from a live session against
onmc v0.7.0. The `Repo root` paths are shortened from the macOS temp dir
(`/private/var/folders/.../tmp.XXX/myapi`) to `/tmp/myapi` for readability.
Task IDs (`task-3c8c1df422`, `artifact-3c4b872ad6`) are real values from that
session run.
