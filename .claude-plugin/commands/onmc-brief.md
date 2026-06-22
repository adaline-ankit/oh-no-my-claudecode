---
description: Compile an onmc task-focused context brief (decisions, invariants, hotspots)
argument-hint: <task description>
allowed-tools: Bash(onmc brief *)
---

<!-- Source: https://code.claude.com/docs/en/agent-sdk/slash-commands (verified 2026-06) -->

Compile an onmc brief for the given task description and present the result.

## Brief

!`onmc brief --task "$ARGUMENTS" --no-llm 2>&1 || echo "onmc not found — run: pip install oh-no-my-claudecode"`

## Task

Review the brief output above compiled by `onmc brief --task "$ARGUMENTS"`. It surfaces
the most relevant repo memories for this task: architectural decisions, known invariants,
hotspot files, and any recorded guardrails. Present the key points to the user so they
can proceed with full context.

If the output says `onmc not found`, instruct the user to install onmc and run
`onmc init && onmc ingest` first.
