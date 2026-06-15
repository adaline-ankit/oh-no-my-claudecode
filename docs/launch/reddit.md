# Reddit post variants

## r/programming

**Title:** I built a git-portable memory layer for coding agents — the brain commits with the repo

---

**Post body:**

Every Claude Code (or Codex, or Cursor) session starts blank. Your agent
re-discovers what broke last sprint, burns thousands of context tokens
reconstructing what you already know, and retries dead-ends it has seen before.

I built `onmc` (oh-no-my-claudecode) to fix this. The short version:

- Memory lives in `.agent-memory/` — plain JSON, committed to git
- Clone any repo that has it and run `onmc sync --restore` → full context instantly
- `onmc guard --task "..."` surfaces recorded dead-ends before the agent touches a line (uses SQLite FTS5, zero LLM calls at guard-time)
- `onmc plug claude-code` / `onmc plug codex` / `onmc plug cursor` wires it into your agent in one idempotent command
- MCP server exposes `search_memory`, `guard_task`, `get_brief` tools

**The benchmark (run it yourself — deterministic, no network, no LLM):**

```
$ onmc bench

                  onmc bench — onmc-builtin-v1
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric                 ┃ Without memory ┃ With memory ┃ Delta ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━┩
│ Repeated-failure rate  │           100% │          0% │ -100% │
│ Wasted attempts        │              9 │           0 │    -9 │
│ Context tokens (proxy) │           4000 │         107 │  -97% │
│ Tasks resolved         │              5 │           5 │    +0 │
└────────────────────────┴────────────────┴─────────────┴───────┘
```

This is a **deterministic simulation** over a synthetic 5-task scenario, not a
live LLM eval — methodology is in `bench/harness.py`. The numbers prove the
mechanism (skip recorded dead-ends, use a compact brief) rather than claiming a
production improvement. Future work: live LLM judge.

**Quickstart:**

```bash
pip install oh-no-my-claudecode
cd your-repo
onmc setup    # ingest git history, generate CLAUDE.md, install hooks + MCP
```

The `.agent-memory/` format is also an open spec (see `AGENT-MEMORY-SPEC.md`)
— any tool can read and write the same brain. `onmc spec validate` checks
conformance.

New project (v0.8.0), no production users yet — launching now. MIT license.

GitHub: https://github.com/adaline-ankit/oh-no-my-claudecode

---

## r/LocalLLaMA

**Title:** onmc — give your local coding agent a persistent brain that commits to git

---

**Post body:**

If you run Claude Code, Codex, or Cursor locally, you know the pain: every
session starts cold. The agent re-discovers constraints, burns context tokens
on things you already know, and sometimes retries approaches that failed three
PRs ago.

`onmc` (oh-no-my-claudecode) is a CLI + MCP server that gives your coding
agent persistent, git-portable memory:

**How it works:**
1. `onmc ingest` reads your git history and docs, extracts structured memories (decisions, invariants, gotchas, failed approaches) into a local SQLite store
2. `onmc sync --commit` exports to `.agent-memory/` — plain JSON that travels with the repo
3. Hooks inject the right subset of memory at session start, on every prompt, and before context compaction
4. `onmc guard` surfaces recorded dead-ends before the agent starts; uses FTS5 — no LLM at guard-time

**Works offline:** guard, brief injection, bench, sync round-trip — all zero LLM calls. Provider config is optional and only used for extraction (`ingest`, `consolidate`, `mine`).

**Cross-agent:** `onmc plug claude-code|codex|cursor|all` — one command, idempotent.

**Open format:** `.agent-memory/` spec is in `AGENT-MEMORY-SPEC.md`. Any tool can be a conformant reader/writer. `onmc spec validate` checks it.

**Proof harness (deterministic, runs in under 5 seconds):**

```
$ onmc bench
Repeated-failure rate: 100% → 0% | Context tokens: -97% | Wasted attempts: -9
(deterministic simulation, synthetic scenario — see bench/harness.py)
```

v0.8.0, MIT, new project. Feedback welcome.

`pip install oh-no-my-claudecode`

GitHub: https://github.com/adaline-ankit/oh-no-my-claudecode
