# Claude Code integration

<!-- Source: https://code.claude.com/docs/en/discover-plugins (verified 2026-06) -->

## Option A — install via plugin marketplace (recommended)

ONMC ships a spec-compliant `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
Add the onmc repository as a marketplace, then install the plugin:

```shell
# 1. Register the onmc marketplace (run once per user or project)
/plugin marketplace add adaline-ankit/oh-no-my-claudecode

# 2. Install the plugin
/plugin install oh-no-my-claudecode@onmc
```

After installing, run `/reload-plugins` to activate hooks, the MCP server, and slash commands.

**What the plugin provides:**

| Component | File | Effect |
|---|---|---|
| MCP server | `.mcp.json` | Starts `onmc serve --mcp` automatically; exposes `search_memory`, `guard_task`, `get_brief`, `record_attempt`, `record_memory`, `list_tasks` |
| `PreCompact` hook | `hooks/hooks.json` | Snapshots task state before context is compacted |
| `SessionStart` hook | `hooks/hooks.json` | Injects boot digest or continuation brief |
| `UserPromptSubmit` hook | `hooks/hooks.json` | Injects the most relevant memories for each prompt |
| `SessionEnd` hook | `hooks/hooks.json` | Runs memory consolidation when the session ends |
| Slash commands | `.claude-plugin/commands/` | `/onmc-why`, `/onmc-guard`, `/onmc-brief`, `/onmc-statusline` (plugin-scoped: invoked as `/onmc:onmc-why` etc.) |

To choose **project scope** (shared with teammates via `.claude/settings.json`) or **user scope**
(all your projects), use the interactive `/plugin` UI instead:

```shell
/plugin
# → Discover → oh-no-my-claudecode → choose scope → Install
```

---

## Option B — one-command install (no marketplace)

```bash
onmc plug claude-code
```

This delegates to `onmc hooks install` and writes:

- `.claude/settings.json` — four project-scoped hooks (idempotent merge, never clobbers
  existing hooks from other tools).
- `.mcp.json` — MCP server registration so Claude Code loads `onmc serve --mcp`
  automatically.
- `.claude/settings.json.onmc-backup` — one-time backup of the pre-install settings.
- `.claude/commands/onmc-*.md` — four project-scoped slash commands (see below).

Re-running `onmc plug claude-code` is always safe.

---

## What gets installed

### Hooks (`.claude/settings.json` or `hooks/hooks.json`)

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

### Slash commands (`.claude/commands/` or plugin-scoped)

Slash commands are available in two ways:

- **Via `onmc plug claude-code`**: project-scoped commands land in `.claude/commands/` and
  are invoked as `/onmc-why`, `/onmc-guard`, `/onmc-brief`, `/onmc-statusline`.
- **Via the plugin marketplace**: plugin-scoped commands from `.claude-plugin/commands/`
  are invoked as `/onmc:onmc-why`, `/onmc:onmc-guard`, etc.

Spec reference: [code.claude.com/docs/en/agent-sdk/slash-commands](https://code.claude.com/docs/en/agent-sdk/slash-commands)

| Command | Argument | What it does |
|---|---|---|
| `/onmc-why <file-path>` | file path | Runs `onmc why <path> --no-llm` and explains why the file looks the way it does (decisions, hotspots, git history) |
| `/onmc-guard <task description>` | task text | Runs `onmc guard --task "..."` and surfaces recorded dead-ends so you never repeat a known failure |
| `/onmc-brief <task description>` | task text | Runs `onmc brief --task "..."` and compiles a task-focused brief (decisions, invariants, hotspots) |
| `/onmc-statusline` | _(none)_ | Runs `onmc statusline` and displays brain health (memory count, freshness, token rate) |

Each command uses the `!`-prefix bash-output mechanism to run `onmc` and embed its
output directly into the model's context before the task instructions.

---

## Manual setup (without `onmc plug` or the plugin)

```bash
onmc hooks install --yes   # same as onmc plug claude-code
```

## First-time memory build

After installing (either way), build the memory store once:

```bash
onmc init && onmc ingest
```

`onmc ingest` reads your git history and extracts decisions, invariants, and hotspots.
On subsequent runs it is incremental.

## Further reading

- [CLI reference: hooks install](../cli-reference.md#onmc-hooks-install)
- [Agent-native workflows](../agent-native-workflows.md)
- [Integration index](README.md)
- [Claude Code plugin docs](https://code.claude.com/docs/en/plugins)
