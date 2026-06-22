---
description: Surface onmc recorded dead-ends so you never retry a known failure
argument-hint: <task description>
allowed-tools: Bash(onmc guard *)
---

<!-- Source: https://code.claude.com/docs/en/agent-sdk/slash-commands (verified 2026-06) -->

Run `onmc guard` for the task and surface any recorded dead-ends.

## Dead-end check

!`onmc guard --task "$ARGUMENTS" --terse 2>&1 || echo "onmc not found — run: pip install oh-no-my-claudecode"`

## Task

Review the output above from `onmc guard --task "$ARGUMENTS"`. If recorded dead-ends
are listed, alert the user clearly: do NOT retry any approach listed. Explain each
dead-end briefly so the user understands what failed and why to avoid it.

If the output says "no recorded dead-ends match this task", confirm that guard
found nothing concerning for this task description.

If the output says `onmc not found`, instruct the user to install onmc and run
`onmc init && onmc ingest` first.
