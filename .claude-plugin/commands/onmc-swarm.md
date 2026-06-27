---
description: Launch a parallel onmc swarm — multiple accountable agent loops running concurrently across isolated git worktrees
argument-hint: <task1> [task2 ...]  OR  --file tasks.txt  [--agent claude|codex|opencode] [--concurrency N] [--max-cost-usd F]
allowed-tools: Bash(onmc swarm *)
---

<!-- Source: https://code.claude.com/docs/en/agent-sdk/slash-commands (verified 2026-06) -->

Launch an onmc swarm — a bounded pool of parallel accountable agent loops.

## Honest concurrency note

A swarm is NOT "N truly simultaneous agent processes." It is a **queue of N tasks
drained by at most `--concurrency` workers** (default: `min(cpu_count-1, 8)`).
API rate limits and RAM are the practical ceiling.

## Swarm run

!`onmc swarm run $ARGUMENTS 2>&1 || echo "onmc not found — run: pip install oh-no-my-claudecode"`

## Task

Review the swarm output above. Each row in the summary table is one loop unit with
its own tamper-evident receipt. Present the key outcomes (done/failed/aborted counts,
total cost) to the user.

Key flags:
- `--task "goal text"` (repeat for multiple tasks) or `--file tasks.txt`
- `--agent claude|codex|opencode` — which agent to use (default: claude)
- `--concurrency N` — bounded pool size (honest: not unlimited parallelism)
- `--max-cost-usd F` — swarm-level total cost ceiling
- `--no-isolate` — skip per-unit git worktree isolation
- `--json` — machine-readable output

To abort a running swarm: `onmc swarm abort <swarm_id>` or `onmc swarm abort --all`

If the output says `onmc not found`, instruct the user to install onmc and run
`onmc init && onmc ingest` first.
