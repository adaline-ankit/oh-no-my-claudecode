---
title: oh-no-my-claudecode
---

# 🧠 oh-no-my-claudecode (onmc)

**Git-portable, cross-agent memory for AI coding agents.** Claude Code, Codex, and
Cursor share one provenanced brain: memory-grounded autonomous loops with verifier
gates, replay, evals, agent-config security auditing, and tamper-evident receipts.

```bash
pipx install oh-no-my-claudecode   # or: pip install oh-no-my-claudecode
onmc init && onmc ingest           # build a brain from your repo
onmc benchmark                     # prove it helps (reproducible numbers)
```

## Documentation

### Start here
- [Architecture](architecture.md) — how the pieces fit together
- [Memory model](memory-model.md) — extraction, provenance, ranking, sync
- [CLI reference](cli-reference.md) — every command
- [Demo walkthrough](demo.md) — two agents, one brain

### Workflows
- [Agent-native workflows](agent-native-workflows.md) — hooks, MCP, per-prompt recall
- [Task lifecycle](task-lifecycle.md)
- [Prompt compiler](prompt-compiler.md)
- [Obsidian export](obsidian.md)
- [Local UI dashboard](ui-dashboard.md)

### Project
- [Shipped capabilities](shipped-capabilities.md)
- [Roadmap](roadmap.md)
- [Releasing](RELEASING.md)

---

Source: [github.com/adaline-ankit/oh-no-my-claudecode](https://github.com/adaline-ankit/oh-no-my-claudecode)
· MIT licensed · [PyPI](https://pypi.org/project/oh-no-my-claudecode/)
