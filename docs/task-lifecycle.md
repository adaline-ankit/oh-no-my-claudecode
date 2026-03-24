# Task Lifecycle

ONMC now treats tasks as first-class local records, not just free-form prompt text.

Each task is stored in `.onmc/memory.db` with:

- `task_id`
- `title`
- `description`
- `status`
- `created_at`
- `started_at`
- `ended_at`
- `repo_root`
- `branch`
- `labels`
- `final_summary`
- `final_outcome`
- `confidence`

## Statuses

- `open`
- `active`
- `blocked`
- `solved`
- `abandoned`

P0 task creation starts tasks in `active`, since the initial CLI entrypoint is `onmc task start`.

## Commands

Start a task:

```bash
onmc task start \
  --title "Fix flaky cache invalidation bug" \
  --description "Investigate cache churn in worker refresh flow" \
  --label bug \
  --label cache
```

List tasks:

```bash
onmc task list
```

Inspect one task:

```bash
onmc task show task-abc123def4
```

Mark a task blocked or active:

```bash
onmc task status task-abc123def4 --status blocked
onmc task status task-abc123def4 --status active
```

End a task with a final summary:

```bash
onmc task end task-abc123def4 \
  --status solved \
  --summary "Fixed cache invalidation churn and updated related tests."
```

## Notes

- task IDs are short and copyable by design
- tasks are scoped to the current repository
- branch is captured when the task starts
- terminal states set `ended_at`
- `final_summary`, `final_outcome`, and `confidence` are schema-ready for richer task memory without requiring more workflow in P0

## Attempts

Tasks can also store attempt records so ONMC preserves what was tried, not just the final outcome.

Each attempt stores:

- `attempt_id`
- `task_id`
- `summary`
- `kind`
- `status`
- `reasoning_summary`
- `evidence_for`
- `evidence_against`
- `files_touched`
- `created_at`
- `closed_at`

Common attempt commands:

```bash
onmc attempt add task-abc123def4 \
  --summary "Try a narrower cache fix first" \
  --kind fix_attempt \
  --status tried \
  --reasoning-summary "The cache module has the strongest churn signal." \
  --file src/cache.py

onmc attempt list task-abc123def4
onmc attempt show attempt-abc123def4
onmc attempt update attempt-abc123def4 \
  --status rejected \
  --evidence-against "The narrowed fix did not touch the failing path."
```

Task detail output includes a compact attempts summary when attempts exist, and task list output includes an attempt count so related attempts are discoverable quickly.
