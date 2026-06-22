---
description: Explain why a file looks the way it does, from onmc memory + git history
argument-hint: <file-path>
allowed-tools: Bash(onmc why *)
---

<!-- Source: https://code.claude.com/docs/en/agent-sdk/slash-commands (verified 2026-06) -->

Run `onmc why` on the given file path and present the result.

## Context

!`onmc why $ARGUMENTS --no-llm 2>&1 || echo "onmc not found — run: pip install oh-no-my-claudecode"`

## Task

Review the output above from `onmc why`. It explains why `$ARGUMENTS` looks the way it
does, drawn from repo memory (architectural decisions, invariants, hotspots) and git
history. Present the key findings to the user: which decisions shaped this file, which
commits changed it most, and any recorded hotspot or invariant warnings.

If the output says `onmc not found`, instruct the user to install onmc and run
`onmc init && onmc ingest` first.
