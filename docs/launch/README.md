# Launch assets

This directory contains launch materials for the public release of
`oh-no-my-claudecode` (onmc).

## Files

| File | Description |
|---|---|
| [`show-hn.md`](show-hn.md) | Show HN post — title options (5), full post body, and anticipated objections with honest answers |
| [`reddit.md`](reddit.md) | r/programming and r/LocalLLaMA variants |
| [`submissions.md`](submissions.md) | Ecosystem list entries and directory submissions *(written by a second agent — do not edit here)* |

## Related

| Link | Description |
|---|---|
| [`docs/demo.md`](../demo.md) | Full "Two Agents, One Brain" walkthrough — all output verified live against v0.7.0 |
| [`AGENT-MEMORY-SPEC.md`](../../AGENT-MEMORY-SPEC.md) | Open spec for the `.agent-memory/` format (version 1) |
| [`docs/integrations/`](../integrations/) | Per-agent integration guides (Claude Code, Codex, Cursor, OMC, OMX) |
| [`docs/cli-reference.md`](../cli-reference.md) | Full generated CLI reference |

## Verified numbers used in all copy

All claims were verified against the live repo before writing. Do not update
these without re-running `onmc bench`.

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
Methodology: deterministic simulation — no LLM calls.
```

## Coordination note

A second agent owns `submissions.md` in this directory. This README and all
other files in `docs/launch/` are owned by the launch-copy agent. Do not
modify `submissions.md` here; do not let the submissions agent modify
`show-hn.md`, `reddit.md`, or this `README.md`.
