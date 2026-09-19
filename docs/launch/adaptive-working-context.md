# Adaptive working context: launch material

Current feature: implemented on `main`, not yet in PyPI `v0.113.0`.
These are copy-and-share assets, not a record of posts already published.

## One-line pitch

Your code changed. Your agent's memory should too.

ONMC keeps Claude Code's task constraints available across compaction and withdraws
recalled claims when their source files change—even before commit.

## Demo

![Adaptive working context demonstration](../assets/working-context-demo.gif)

[Download GIF](../assets/working-context-demo.gif)
· [Static card](../assets/working-context-demo.png)
· [Underlying results](../assets/working-context-demo.json)

The animation renders results from `scripts/demo-working-context.py`. It uses
real temporary Git files, SQLite, and ONMC's hook dispatcher, with no model calls.
It is not a recording of a live Claude session.

Suggested narration:

1. “ONMC recalls that the cache TTL is 30 seconds.”
2. “Change the source to 60 seconds. Keep the same file timestamp.”
3. “The old claim is withdrawn: its source content changed.”
4. “Reload the working state. The API constraint and next step are still there.”
5. “Ask for the same packet again: zero extra characters.”

## Short post

I built adaptive working context for Claude Code.

It keeps the task goal, constraints, decisions, and next step available across
compaction. When a recalled fact's source file changes, ONMC withdraws that fact.
Unchanged context stays quiet.

Local SQLite. No model calls for context compilation. Every exclusion inspectable.

The demo checks real files and hooks. The live Codex pilot tied at 3/3 tasks per
arm—no claim of improved coding accuracy yet.

Try it from main: https://github.com/adaline-ankit/oh-no-my-claudecode

## Show HN draft

**Title:** Show HN: ONMC – working context that notices when its source code changes

Coding agents already write impressive code. I wanted the task's constraints and
supporting evidence to stay useful as a session gets long and the repository changes.

ONMC stores session goals, constraints, decisions, and next steps locally. Its
context compiler checks recalled memory against source contents, excludes stale
claims, fits whole items into a character budget, and suppresses unchanged packets.
Claude Code hooks deliver it around prompts/tools and restore it after compaction.
Other MCP clients can use explicit sessions through the same store.

The attached demo changes a file without changing its timestamp. ONMC still
withdraws the earlier claim. It uses actual Git, SQLite, and hook results; no model
calls. The repo includes the script, raw results, component benchmarks, and a
small live Codex pilot that tied 3/3 vs 3/3.

This cannot erase text already in the model's conversation or guarantee that the
agent obeys a constraint. I would especially value long-session failure cases and
independent benchmark replications.

## Engineering post

A coding agent can remember the right fact from yesterday and apply it to the
wrong code today.

I added a local working-context compiler to ONMC. The hard parts were source
identity, concurrent hook updates, isolation between sessions, and delivery:

- File content checks catch dirty edits and timestamp-preserving changes.
- SQLite transactions preserve concurrent note updates.
- Whole-item packing keeps the goal and pinned constraints intact.
- Packet fingerprints suppress repeated context; resume/compaction forces refresh.
- Eligibility reasons distinguish stale, missing, unanchored, and conflicting evidence.

The internal event suite passed 117/117 adaptive eligibility/delivery checks.
At 10,000 synthetic memories, in-process compilation measured 2.48 ms median on
one Apple M4. These are component measurements, not coding-success metrics.
The live Codex pilot tied at 3/3 tasks per arm. The next test is a larger held-out
long-session corpus.

Code, protocol, and artifacts: https://github.com/adaline-ankit/oh-no-my-claudecode

## Claims that the evidence supports

- “117/117 internal synthetic eligibility/delivery checks.”
- “36.5% fewer injected characters than forced-refresh adaptive packets in that suite.”
- “2.48 ms median in-process compilation at 10,000 synthetic memories on one Apple M4.”
- “The live Codex pilot tied at 3/3 tasks per arm.”

Avoid “never forgets,” “perfect reliability,” “36.5% cheaper coding,” or “beats Claude.”
The benchmark measures different quantities, and none supports those claims.
See the [protocol](../benchmarks/working-context.md) before reusing a number.
