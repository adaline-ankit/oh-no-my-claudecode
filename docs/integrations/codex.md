# Codex / GitHub Coding Agent integration

Codex reads `AGENTS.md` at the start of every session.  `onmc plug codex` writes
a managed stanza into that file so Codex always runs `onmc brief` and `onmc guard`
before it starts working.

## One-command install

```bash
onmc plug codex
```

This writes (or refreshes) a delimited stanza in `AGENTS.md`.  The stanza is
idempotent — running twice produces exactly one copy.

## What gets written

A block between `<!-- onmc-plug:codex -->` markers is appended to (or updated
in) `AGENTS.md`:

```markdown
## Using ONMC memory (managed by `onmc plug codex`)

# 1. Get a task-focused context brief (fast, no LLM)
onmc brief --task "$TASK" --stdout

# 2. Surface recorded dead-ends — never repeat a known failure
onmc guard --task "$TASK"

# 3. (Optional) MCP tools mid-session
onmc serve --mcp &
```

Codex sees these instructions on every run and calls the commands before
executing the user's task.

## Fresh clone / cloud container

For GitHub Coding Agent or other cloud containers, add this to your container
startup (e.g. `.devcontainer/devcontainer.json` `postCreateCommand`):

```bash
pip install oh-no-my-claudecode
onmc init && onmc sync --restore
```

The `onmc sync --restore` step replays the committed `.agent-memory/` JSON in
under a second — no re-ingestion, no LLM call.

## MCP tool access

Start the MCP server once at session begin:

```bash
onmc serve --mcp &
```

Available tools: `search_memory`, `guard_task`, `get_brief`.

## Further reading

- [CLI reference: brief](../cli-reference.md#onmc-brief)
- [CLI reference: guard](../cli-reference.md#onmc-guard)
- [Integration index](README.md)
