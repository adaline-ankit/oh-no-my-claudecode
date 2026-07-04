---
name: Bug report
about: Report a reproducible problem in ONMC
title: "[Bug] "
labels: kind/bug, needs-triage
assignees: ""
---

## Summary

What broke? Include the exact command you ran.

## Impact

- Priority guess: `P0` / `P1` / `P2` / `P3`
- Who is blocked?
- Is there data loss, security exposure, or a broken release?

## Steps To Reproduce

1.
2.
3.

## Expected Behavior

## Actual Behavior

Paste the full error output or traceback if available.

## Environment

- Python version:
- OS:
- ONMC version:
- Install method: `pip`, `pipx`, source checkout, other
- Agent integration: Claude Code hooks, MCP server, Codex/AGENTS.md, other

## Additional Context

If the bug involves generated memory, attach sanitized snippets from `.agent-memory/` or
`CLAUDE.md`. Do not paste API keys, tokens, private prompts, or proprietary source code.
