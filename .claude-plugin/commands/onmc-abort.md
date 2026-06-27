---
description: Abort a running onmc swarm (or all swarms) by writing an ABORT sentinel file
argument-hint: <swarm_id>  OR  --all
allowed-tools: Bash(onmc swarm abort *)
---

<!-- Source: https://code.claude.com/docs/en/agent-sdk/slash-commands (verified 2026-06) -->

Request graceful abort of an onmc swarm or all running swarms.

## Abort

!`onmc swarm abort $ARGUMENTS 2>&1 || echo "onmc not found — run: pip install oh-no-my-claudecode"`

## Task

Report the abort result to the user. Explain that:
- Abort is **graceful** — running units finish their current iteration, then stop.
- Queued units that haven't started yet are never launched.
- The ABORT sentinel file is written to `.onmc/swarm/<swarm_id>/ABORT` (or `.onmc/swarm/ABORT` for `--all`).
- To check swarm status after aborting: `onmc swarm status` or `onmc swarm list`

Usage:
- `onmc swarm abort <swarm_id>` — abort one specific swarm
- `onmc swarm abort --all` — abort all running swarms via global sentinel

If the output says `onmc not found`, instruct the user to install onmc and run
`onmc init && onmc ingest` first.
