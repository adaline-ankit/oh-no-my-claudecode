---
description: Run an onmc swarm — fan out parallel accountable agents. Defaults to token-free in-session subagents; falls back to process swarm.
argument-hint: <task1> [task2 ...]  OR  --file tasks.txt   [--concurrency N]  [--process]
allowed-tools: Task, Bash(onmc swarm *)
---

<!-- Source: https://code.claude.com/docs/en/agent-sdk/slash-commands (verified 2026-06) -->

Run an onmc swarm: fan multiple accountable agents out in parallel, each with its
own tamper-evident receipt.

## Two modes (pick based on `$ARGUMENTS`)

- **In-session (default, token-free).** Claude Code spawns the workers as
  **subagents** via the Task tool. They inherit this session's authentication —
  **no API key or OAuth token is needed.** onmc is the accountability ledger.
  Bounded by Claude Code's own subagent cap (~10 at once), so batch.
- **Process mode (`--process`).** Shells out to independent `claude -p` /
  `codex` / `opencode` processes (`onmc swarm run …`). Bigger scale + hard-kill,
  but each process must authenticate on its own (keychain login or an exported
  token). Use when the user passed `--process`.

Honest either way: a swarm is a **queue drained by a bounded pool**, not N truly
simultaneous agents.

## If `--process` is present

Run `!onmc swarm run $ARGUMENTS` (strip the `--process` flag first), then
summarize the table. Done.

## Otherwise — drive the in-session swarm

1. **Allocate** the swarm (no model call, no spend):

   `onmc swarm plan $ARGUMENTS --json`  (pass through `--task`/`--file`/`--concurrency`)

   Parse the JSON: `swarm_id`, `abort_path`, and `units` (each `{id, goal}`).

2. **Fan out.** Launch one **subagent via the Task tool per unit**, up to the
   recommended `concurrency` at a time (send multiple Task calls in a single
   message to run them concurrently). Give each subagent its unit's `goal`,
   tell it to do the work and report back: what it did, whether it met the
   goal, and which files it touched. **Before launching each batch, check
   whether `abort_path` exists** — if it does, stop launching new units.

3. **Record** each finished unit (honest — `--verified` only if the success
   criteria were actually met):

   `onmc swarm record <swarm_id> <unit_id> --goal "<goal>" --summary "<what it did>" [--verified] [--files a.py,b.py]`

   For an aborted/never-started unit use `--aborted`.

4. **Summarize** with `onmc swarm status <swarm_id>` and report done/failed/
   aborted counts + the receipt paths to the user.

To abort mid-run: `onmc swarm abort <swarm_id>` (or `--all`) — writes the
sentinel the fan-out checks between batches.

If `onmc` is not found, tell the user to `pip install oh-no-my-claudecode` and
run `onmc init` first.
