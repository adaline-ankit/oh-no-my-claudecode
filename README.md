# oh-no-my-claudecode (`onmc`)

[![CI](https://github.com/adaline-ankit/oh-no-my-claudecode/actions/workflows/ci.yml/badge.svg)](https://github.com/adaline-ankit/oh-no-my-claudecode/actions)
[![PyPI version](https://badge.fury.io/py/oh-no-my-claudecode.svg)](https://pypi.org/project/oh-no-my-claudecode/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![AI-Ready](https://img.shields.io/badge/AI--Ready-ONMC-6B7280)](https://github.com/adaline-ankit/oh-no-my-claudecode)

> Repo-native memory for AI coding agents.  
> Your agent knows your codebase history, not just its current state.

---

## Get started

```bash
pip install oh-no-my-claudecode
onmc setup
```

That's it. `onmc setup` reads your git history, extracts architectural decisions and invariants, generates `CLAUDE.md`, and connects to Claude Code — all in one interactive wizard.

---

## What it does

Your coding agent starts every session like it has never seen your codebase before. It doesn't know why the code looks the way it does, what was tried and failed, or which files are dangerous to change. **ONMC fixes that.**

It reads your git history, docs, and code structure with an LLM and builds a structured memory store. That memory travels with the repo. Every agent — Claude Code, Cursor, Codex — gets it.

---

## Works with every coding agent

| Agent | Integration |
|---|---|
| **Claude Code** | `onmc hooks install` + `onmc serve --mcp` |
| **Cursor** | Pipe `onmc brief` output to `.cursorrules` |
| **Codex CLI** | Pass `onmc brief` output via `AGENTS.md` |
| **Cloud agents** (Codex, GitHub Coding Agent) | `onmc sync --restore` in container startup |
| **Gitpod / Codespaces** | Add `onmc sync --restore` to `.gitpod.yml` |

---

## Commands

### Setup and health

```bash
onmc setup              # full onboarding wizard — run this first
onmc doctor             # health check: memory freshness, hooks, MCP, CLAUDE.md
onmc status             # repo root, ingest state, memory counts
```

### Memory extraction

```bash
onmc ingest             # scan git history, docs, source — extract structured memory
onmc ingest --files x   # re-ingest specific files
onmc ingest --install-hook  # auto-ingest on every commit
onmc mine               # extract memory from Claude Code session transcripts
onmc mine --github      # extract decisions and gotchas from GitHub PRs
```

### Memory management

```bash
onmc memory list                    # browse all memory
onmc memory list --kind hotspot     # filter by kind
onmc memory list --type did_not_work
onmc memory show <id>               # full record with provenance
onmc memory confirm <id>            # mark as verified useful
onmc memory reject <id>             # mark as wrong or stale
onmc memory edit <id>               # update the summary
onmc memory add <task_id> --type fix --title "..." --summary "..."
```

### CLAUDE.md

```bash
onmc claude-md generate  # generate CLAUDE.md from memory store
onmc claude-md update    # refresh stale sections, preserve user-written ones
onmc claude-md preview   # show what would be generated without writing
onmc claude-md --watch   # auto-regenerate when memory changes
```

### Tasks and attempts

```bash
onmc task start --title "..." --description "..."
onmc task list / show / status / end
onmc attempt add <task_id> --summary "..." --kind fix_attempt --status tried
onmc attempt list / show / update
```

### Brief compilation

```bash
onmc brief --task "fix the cache invalidation bug"
# LLM-ranked, annotated with relevance reasons
# Written to .onmc/compiled/ and rendered in terminal
```

### Agent modes (optional LLM)

```bash
onmc solve --task "..." --task-id <id>     # next best engineering approach
onmc review --task "..." --input-file plan.md
onmc teach --task "..."                     # staff-engineer explanation
onmc teach --task "..." --interactive       # follow-up Q&A loop
```

### Claude Code integration

```bash
onmc hooks install      # compaction hooks — context survives every compact
onmc hooks status
onmc serve --mcp        # read-only MCP server for mid-session memory queries
```

### Git-portable memory

```bash
onmc sync --commit      # export memory to .agent-memory/ (commit this)
onmc sync --restore     # restore memory on a fresh machine or cloud env
onmc sync --install-hook
```

### LLM provider

```bash
onmc llm configure --provider anthropic --model claude-sonnet-4-5
onmc llm status
```

---

## Python API

```python
import onmc

repo = onmc.init(".")
repo.ingest()
brief = repo.brief(task="fix the cache invalidation bug")
memories = repo.memory.search(files=["src/cache.py"])
task = repo.task.start(title="Fix cache bug")
repo.sync.commit()
```

---

## How memory travels with your repo

```bash
onmc sync --commit
git add .agent-memory/
git commit -m "chore: export agent memory"
git push
```

Any machine that clones this repo — cloud agent, new teammate, ephemeral container — runs:

```bash
onmc init && onmc sync --restore
```

And gets the full memory store instantly. No accounts. No cloud. No config.

---

## Local state

```text
.onmc/            ← gitignored (binary SQLite + logs)
.agent-memory/    ← commit this (readable JSON exports)
CLAUDE.md         ← commit this (generated by onmc claude-md generate)
```

---

## Platform support

macOS and Linux. Windows support planned for v0.4.0.

---

## Development

```bash
git clone https://github.com/adaline-ankit/oh-no-my-claudecode
cd oh-no-my-claudecode
pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Good first issues are labeled in the tracker.

Areas actively looking for contributors:
- Cursor hook adapter
- Embedding-based memory ranking (opt-in)
- VS Code extension for brief display
- Semantic transcript-to-task linking

---

## License

MIT. See [LICENSE](LICENSE).
