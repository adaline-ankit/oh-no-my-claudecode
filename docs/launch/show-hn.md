# Show HN: oh-no-my-claudecode — git-portable memory for coding agents

## Title options (pick one)

1. **Show HN: oh-no-my-claudecode – git-portable memory for Claude Code, Codex, and Cursor**
2. **Show HN: I built a memory layer for coding agents that travels with the repo**
3. **Show HN: onmc – agents share a brain via .agent-memory/ committed to git**
4. **Show HN: Give your coding agent a persistent brain it never forgets across sessions**
5. **Show HN: Agents have amnesia. onmc is the fix (open spec + ref impl, MIT)**

Recommended: **#1** (most searchable) or **#3** (leads with the mechanism, unusual angle).

---

## Post body

---

Every Claude Code session starts blank. Your agent re-discovers that the cache layer can't be mocked, re-tries the auth approach that broke CI three sprints ago, and burns 4,000 context tokens reconstructing what you already knew. Every. Single. Session.

I built **oh-no-my-claudecode** (`onmc`) to fix that.

**What it does:** reads your git history, session transcripts, and docs; builds a structured memory store in `.agent-memory/` (committable JSON); and injects the right knowledge at session start, on every prompt, and before context compaction. The brain travels with the repo — clone it anywhere and get full memory back in seconds.

**The proof — run it yourself (deterministic, no LLM, no network):**

```
$ onmc bench
```

```
                  onmc bench — onmc-builtin-v1
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric                 ┃ Without memory ┃ With memory ┃ Delta ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━┩
│ Repeated-failure rate  │           100% │          0% │ -100% │
├────────────────────────┼────────────────┼─────────────┼───────┤
│ Wasted attempts        │              9 │           0 │    -9 │
├────────────────────────┼────────────────┼─────────────┼───────┤
│ Context tokens (proxy) │           4000 │         107 │  -97% │
├────────────────────────┼────────────────┼─────────────┼───────┤
│ Tasks resolved         │              5 │           5 │    +0 │
└────────────────────────┴────────────────┴─────────────┴───────┘
```

**Honest caveat on the numbers:** this is a deterministic simulation over a
synthetic 5-task scenario — not a live LLM evaluation. It models an agent
executing tasks under two conditions: without onmc (rediscovers context from
scratch, retries known dead-ends) and with onmc (brief + recall injected,
`failed_approach` memories block repeated mistakes). Results are identical
across runs because no LLM is called. The harness is in `bench/harness.py` if
you want to inspect or extend it.

**One command to adopt, works with your existing agent:**

```bash
pip install oh-no-my-claudecode
cd your-repo
onmc plug claude-code    # hooks + .mcp.json — one idempotent command
# or:
onmc plug codex          # AGENTS.md stanza
onmc plug cursor         # .cursor/rules/onmc.md
onmc plug all            # all three
```

**The insight that made this work:** instead of storing memory in a proprietary
cloud or a per-machine database, the memory lives in `.agent-memory/` — plain
JSON files committed to git. Any agent that clones the repo gets the full brain
instantly. A CI agent, a new teammate, an ephemeral Codespaces container — all
get the same knowledge. No accounts. No config. No sync service.

**The key commands:**

- `onmc guard --task "..."` — before your agent starts, surfaces every recorded
  dead-end matching the task. Uses SQLite FTS5 + token reranking; no LLM at
  guard-time.
- `onmc why <file>` — explains why a file looks the way it does, from stored
  memory + git history. `--at <commit>` for time-travel.
- `onmc brief --task "..."` — compiles a task-specific context brief (LLM-ranked,
  annotated with relevance reasons).
- `onmc consolidate` — self-improvement pass: dedup, merge, promote/demote,
  build a memory-edge graph. Also runs as a SessionEnd hook.
- `onmc mine` — extracts memory from Claude Code session transcripts
  automatically.
- `onmc sync --commit` / `onmc sync --restore` — git-portable round-trip.
- `onmc serve --mcp` — MCP server exposing `search_memory`, `guard_task`,
  `get_brief` tools to any MCP-capable agent.
- `onmc bench` — run the benchmark above.

**The open spec:** the `.agent-memory/` format is documented in
[`AGENT-MEMORY-SPEC.md`](../../AGENT-MEMORY-SPEC.md) as an open versioned
standard. Any tool can be a conformant reader or writer. We ship
`onmc spec validate` to check conformance. The goal is interoperability — if
you use Cursor today and Claude Code tomorrow, neither agent should lose its
memory.

**Quickstart:**

```bash
pip install oh-no-my-claudecode
cd your-repo
onmc setup          # wizard: ingest git history, generate CLAUDE.md,
                    # install hooks + MCP
onmc sync --commit
git add .agent-memory/ CLAUDE.md
git commit -m "chore: add onmc agent brain"
```

On a fresh clone or cloud agent container:

```bash
onmc init && onmc sync --restore   # full memory, zero re-discovery
```

GitHub: https://github.com/adaline-ankit/oh-no-my-claudecode  
PyPI: `pip install oh-no-my-claudecode`

---

## Anticipated HN objections — honest answers

**"Isn't this just claude-mem / mem0 / MemGPT?"**

Those are primarily cloud services or in-process vector databases, often requiring
an account and a sync service. onmc's distinguishing property is that the memory
is plain JSON committed to git — no cloud dependency, no account, works in
air-gapped environments, survives ephemeral containers, and every agent that
clones the repo gets the same brain. The AGENT-MEMORY-SPEC is also a
cross-agent open format, not tied to any specific agent.

**"LLM near production? That sounds like a bad idea."**

The hot path (guard, brief injection, statusline) makes zero LLM calls.
LLM calls happen only during `onmc ingest` (extracting memories from git
history and docs) and `onmc consolidate` (self-improvement between sessions),
and only when you configure a provider with `onmc llm configure`. The guard
harness, the bench, and the sync round-trip all work fully offline. `onmc setup
--no-llm` skips all LLM steps on first run.

**"Does the memory actually help, or is this just vibes?"**

Run `onmc bench` yourself — the harness is open source and the numbers are
identical across runs because it is a deterministic simulation, not a black
box. The methodology is synthetic (5-task scenario, seeded memory store), which
is a real limitation we acknowledge explicitly in the README. Future work:
replace the simulation policy with a live LLM judge. But the deterministic
harness does prove the mechanism works: with recorded dead-ends, the agent
skips them; with a compact brief, context usage drops.

**"Why Python, not a TypeScript plugin?"**

The CLI and MCP server are Python because the LLM extraction, the SQLite
store, and the rich TUI are easier to maintain there. The agent integration
(Claude Code hooks, `.mcp.json`, `CLAUDE.md`) is agent-agnostic — it just
calls the `onmc` binary. The Python API is also exposed if you want to embed it.

**"Won't .agent-memory/ bloat my repo?"**

Each memory entry is a small JSON file (under 2 KB). A repo with hundreds of
memories stays well under 1 MB of committed files. The local `.onmc/` directory
(SQLite, logs) is gitignored by default.

**"Is it stable?"**

This is new software — v0.8.0, released today. The format spec is versioned
(currently `"1"`) with forward-compatibility rules so readers must ignore
unknown fields. We have an end-to-end test suite (`tests/test_e2e.py`) that
drives the full lifecycle. No production users yet to report; we are launching
now. Expect rough edges; please file issues.
