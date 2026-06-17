# Agent Integration Guides

Use `onmc plug <agent>` to wire onmc into your coding agent in one command.
All writes are idempotent — re-running never duplicates stanzas.

## Quickstart

### Claude Code (one step via plugin marketplace)

```shell
# Inside Claude Code:
/plugin marketplace add adaline-ankit/oh-no-my-claudecode
/plugin install oh-no-my-claudecode@onmc
/reload-plugins
```

The plugin activates four lifecycle hooks and the `onmc` MCP server automatically.
See [claude-code.md](claude-code.md) for the alternative `onmc plug claude-code` path.

### Codex (two steps)

```bash
# Write the AGENTS.md stanza Codex reads at every session start:
onmc plug codex

# Register the MCP server in ~/.codex/config.toml:
codex mcp add onmc -- onmc serve --mcp
```

See [codex.md](codex.md) for the full `~/.codex/config.toml` format.

---

## All plug targets

```bash
onmc plug claude-code   # hooks + .mcp.json for Claude Code
onmc plug codex         # AGENTS.md stanza for Codex / GitHub Coding Agent
onmc plug cursor        # .cursor/rules/onmc.md for Cursor
onmc plug omc           # copy-paste adapter for oh-my-claudecode (OMC)
onmc plug omx           # copy-paste adapter for oh-my-codex (OMX)
onmc plug all           # claude-code + codex + cursor in one pass
```

## Integration guides

| Agent | Guide | What `onmc plug` writes |
|---|---|---|
| Claude Code | [claude-code.md](claude-code.md) | `.claude/settings.json` hooks + `.mcp.json` |
| Codex / GitHub Coding Agent | [codex.md](codex.md) | `AGENTS.md` stanza |
| Cursor | [cursor.md](cursor.md) | `.cursor/rules/onmc.md` |
| oh-my-claudecode (OMC) | [omc.md](omc.md) | `docs/integrations/omc.md` (copy-paste adapter) |
| oh-my-codex (OMX) | [omx.md](omx.md) | `docs/integrations/omx.md` (copy-paste adapter) |

## What onmc adds to every agent

- **`onmc brief --task "..."`** — relevant repo memories, hotspots, and
  architectural decisions, compiled in under a second.
- **`onmc guard --task "..."`** — recorded dead-ends so the agent skips
  known failures.
- **`onmc serve --mcp`** — MCP tools (`search_memory`, `guard_task`,
  `get_brief`) for mid-session recall.

The pitch: **OMC/OMX + onmc = an orchestrator that never repeats yesterday's failure.**
