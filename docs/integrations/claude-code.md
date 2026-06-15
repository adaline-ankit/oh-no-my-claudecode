# Claude Code integration

## One-command install

```bash
onmc plug claude-code
```

This delegates to `onmc hooks install` and writes:

- `.claude/settings.json` — four project-scoped hooks (idempotent merge, never clobbers
  existing hooks from other tools).
- `.mcp.json` — MCP server registration so Claude Code loads `onmc serve --mcp`
  automatically.
- `.claude/settings.json.onmc-backup` — one-time backup of the pre-install settings.

Re-running `onmc plug claude-code` is always safe.

## What gets installed

### Hooks (`.claude/settings.json`)

| Event | Command | Effect |
|---|---|---|
| `PreCompact` | `onmc hooks pre-compact` | Snapshots task state before context is compacted |
| `SessionStart` | `onmc hooks session-start` | Injects boot digest (startup) or continuation brief (post-compact) |
| `UserPromptSubmit` | `onmc hooks prompt-recall` | Injects the most relevant memories for each prompt |
| `SessionEnd` | `onmc hooks session-end` | Runs memory consolidation when the session ends |

### MCP server (`.mcp.json`)

```json
{
  "mcpServers": {
    "onmc": {
      "command": "onmc",
      "args": ["serve", "--mcp"]
    }
  }
}
```

MCP tools exposed: `search_memory`, `guard_task`, `get_brief`, `record_attempt`, `record_memory`, `list_tasks`.

## Alternative: use the plugin manifest

If you use the Claude Code plugin marketplace, the plugin manifest at
[`.claude-plugin/plugin.json`](../../.claude-plugin/plugin.json) registers hooks
and the MCP server automatically.

## Manual setup (without `onmc plug`)

```bash
onmc hooks install --yes   # same as onmc plug claude-code
```

## Further reading

- [CLI reference: hooks install](../cli-reference.md#onmc-hooks-install)
- [Agent-native workflows](../agent-native-workflows.md)
- [Integration index](README.md)
