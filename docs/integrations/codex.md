# Codex / GitHub Coding Agent integration

<!-- Source: https://developers.openai.com/codex/config-reference (verified 2026-06) -->

Codex reads `AGENTS.md` at the start of every session and resolves MCP servers from
`~/.codex/config.toml` or `.codex/config.toml`. `onmc plug codex` writes a managed
stanza into `AGENTS.md` instructing Codex to run `onmc brief` and `onmc guard` before it
starts working.

## One-command install

```bash
onmc plug codex
```

This writes (or refreshes) a delimited stanza in `AGENTS.md`.  The stanza is
idempotent — running twice produces exactly one copy.

## What gets written in AGENTS.md

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

These instructions ask Codex to call the commands before working. As with other
agent instructions, compliance is not guaranteed.

---

## MCP server configuration (copy-paste)

Add the following to `~/.codex/config.toml` (user-level, all projects) or
`.codex/config.toml` (project-level) to give Codex access to onmc MCP tools
(`search_memory`, `guard_task`, `get_brief`) mid-session.

```toml
# ~/.codex/config.toml  or  .codex/config.toml
# onmc — repo-native memory MCP server
[mcp_servers.onmc]
command = "onmc"
args = ["serve", "--mcp"]
enabled = true
```

Or use the `codex mcp add` command:

```bash
codex mcp add onmc -- onmc serve --mcp
```

After adding, verify:

```bash
codex mcp list
```

Codex MCP servers are loaded at startup; restart Codex after editing
`config.toml`.

### MCP tools available once configured

| Tool | Purpose |
|---|---|
| `search_memory` | Ranked search over repo decisions, invariants, hotspots |
| `guard_task` | Ranked list of recorded dead-ends for a task |
| `get_brief` | Compile a task-focused brief on demand |

---

## Adaptive working context (main)

Install ONMC from Git `main` for this feature; it is ahead of PyPI `v0.113.0`.
After `onmc working enable`, MCP clients can use `start_working_context`,
`get_working_context`, and `record_working_note` with an explicit session ID.
CLI commands provide the same access. Native automatic hook delivery currently
supports Claude Code; enabling does not add equivalent Codex lifecycle hooks.

See [working context](../working-context.md) for setup, source checks, session
isolation, and advisory-instruction limits. Working notes remain local and are
not included in `.agent-memory` exports.

## Fresh clone / cloud container

For GitHub Coding Agent or other cloud containers, add this to your container
startup (e.g. `.devcontainer/devcontainer.json` `postCreateCommand`):

```bash
pip install oh-no-my-claudecode
onmc init && onmc sync --restore
```

The `onmc sync --restore` step replays the committed `.agent-memory/` JSON in
under a second — no re-ingestion, no LLM call.

Then run at session start:

```bash
onmc brief --task "..." --stdout
onmc guard --task "..."
```

## Further reading

- [CLI reference: brief](../cli-reference.md#onmc-brief)
- [CLI reference: guard](../cli-reference.md#onmc-guard)
- [Codex CLI config reference](https://developers.openai.com/codex/config-reference)
- [Integration index](README.md)
