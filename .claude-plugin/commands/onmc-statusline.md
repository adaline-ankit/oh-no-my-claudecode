---
description: Show onmc brain health statusline (memory count, freshness, token rate)
allowed-tools: Bash(onmc statusline)
---

<!-- Source: https://code.claude.com/docs/en/agent-sdk/slash-commands (verified 2026-06) -->

Run `onmc statusline` and display the current brain health summary.

## Brain health

!`onmc statusline 2>&1 || echo "onmc not found — run: pip install oh-no-my-claudecode"`

## Task

Display the brain health line shown above. It summarises the repo memory store:
memory count, freshness percentage, stale entries, and token activity rate. If the
output says `onmc not found`, instruct the user to install onmc.
