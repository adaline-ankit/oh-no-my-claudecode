# Cursor integration

Cursor >=0.40 reads markdown rule files from `.cursor/rules/`.
`onmc plug cursor` writes `.cursor/rules/onmc.md` so Cursor always knows
to run `onmc brief` and `onmc guard` before starting any task.

## One-command install

```bash
onmc plug cursor
```

This writes (or refreshes) `.cursor/rules/onmc.md`.  The file is idempotent —
running twice produces exactly one copy.

## What gets written

`.cursor/rules/onmc.md` contains:

```markdown
## ONMC memory context

Before starting any task, run in the terminal:

onmc brief --task "DESCRIBE YOUR TASK" --stdout
onmc guard --task "DESCRIBE YOUR TASK"

`onmc brief` returns the most relevant repo memories, hotspots, and
architectural decisions for your task.  `onmc guard` lists recorded
dead-ends so you never retry a known failure.
```

Cursor injects this file into every session's context automatically.

## Older Cursor versions (pre-0.40)

Cursor <0.40 reads `.cursorrules` (a flat file) instead of `.cursor/rules/`.
To support older versions, copy the stanza into your `.cursorrules` file:

```bash
onmc brief --task "describe your task" --stdout >> .cursorrules
```

Or pipe it fresh at the start of each session from the Cursor terminal:

```bash
onmc brief --task "$(cursor_task_description)" --stdout
```

## MCP server

Start the onmc MCP server in the Cursor terminal:

```bash
onmc serve --mcp &
```

Then use the `search_memory`, `guard_task`, and `get_brief` tools in any
Cursor agent session.

## Further reading

- [CLI reference: brief](../cli-reference.md#onmc-brief)
- [CLI reference: guard](../cli-reference.md#onmc-guard)
- [Integration index](README.md)
