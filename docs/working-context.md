# Adaptive working context

ONMC keeps a task's goal, constraints, decisions, hypotheses, and next step
available as Claude moves between files and compacts its conversation. It checks
recalled memories against current source contents and tells Claude when earlier
evidence is no longer current.

## Start using it

This feature is available from `main` until the next package release:

```bash
uv tool install --force 'git+https://github.com/adaline-ankit/oh-no-my-claudecode.git@main'
```

From an initialized project:

```bash
onmc init  # only needed if the project is not initialized
onmc working enable \
  --constraint "Preserve existing public APIs" \
  --constraint "Add no new runtime dependencies" \
  --budget-chars 6000
claude
```

Enablement installs project hooks and ONMC's project MCP registration. Start a
new Claude session or resume after enabling so Claude reloads hook settings.
Existing custom hooks are preserved. Each real Claude `session_id` gets its own
working state. The first prompt establishes its goal; subsequent prompts update
focus without silently replacing that goal. Configured constraints are copied
when a session starts; changing defaults does not rewrite an existing task.

The packet prints the session ID. Claude can use `record_working_note` to save a
decision, hypothesis, or next step and `get_working_context` to refresh its
packet. Other MCP clients can use `start_working_context` with an explicit session
ID and goal. All three tools require working context to be enabled.

For a terminal-driven workflow:

```bash
onmc working start --session cache-fix --task "Fix cache expiration" \
  --constraint "Preserve the public cache API"
onmc working note --session cache-fix --kind hypothesis \
  --text "TTL conversion may cause the timeout" --file src/cache.py
onmc working note --session cache-fix --kind next_step \
  --text "Add a boundary regression and run the cache tests"
onmc working context --session cache-fix --file src/cache.py
onmc working context --session cache-fix --json
```

A named CLI session is independent of Claude's automatically created session.
Use the ID shown in Claude's packet to inspect or update that actual session.
CLI inspection does not consume the next hook delivery. Replacing a goal or
constraints requires explicit `working start --replace`; MCP cannot replace them.

## What adapts

| Event | Behavior |
|---|---|
| First user prompt | Create that session's goal and copy configured constraints |
| Later prompt | Update current focus; retain goal and constraints |
| Read/edit/write/shell tool boundary | Refresh relevant context and recheck file anchors |
| Source content changes | Exclude affected memories; label anchored notes for rechecking |
| Packet unchanged | Emit no repeated context |
| Context refresh fails, then recovers | Emit an unavailable notice, then deliver a fresh packet |
| Session resume or compaction | Emit full current goal, constraints, notes, and eligible memory |
| Explicit memory conflict | Exclude both eligible conflicting entries; report conflict |

When enabled, the working packet owns these context delivery paths, replacing
legacy prompt recall and pre-edit/continuation injection. This prevents legacy
recall from reintroducing a stale entry the new engine rejected. Existing
telemetry continues. Child-agent events with `agent_id` do not consume the main
session's packet; independent child working-state delivery is not implemented.

## Evidence freshness and trust

Source hashes are tied to the memory's contents and trust metadata. Initial
automatic binding requires a clean tracked source whose last commit predates
the memory. File content is compared with Git's stored object, including when
Git marks a file assume-unchanged. Later packets compare content hashes, so dirty
edits and timestamp-preserving changes are visible. Every declared file in a
pipe-separated source reference is checked, including extensionless files and
dotfiles. Provenance such as `manual:review | ./src/cache.py:12` is parsed per
reference, so the provenance prefix cannot bypass the file freshness check.
Active-file retrieval accepts the same whitespace and `./` forms. Directory
references are excluded as unavailable; directory hashing is not supported.

Dirty/untracked sources require explicit acknowledgement after reviewing the
memory against the current file:

```bash
onmc working verify-memory MEMORY_ID
```

This records source identity. It does **not** certify the statement, update its
text, or promote a quarantined memory. A later memory/source change invalidates
the acknowledgement. Missing files, out-of-repository paths, escaping symlinks,
and oversized source files are excluded. Memories without file anchors are
labeled `unanchored`; they have no content-based freshness guarantee.

Autonomous quarantined memories and explicitly rejected entries are excluded.
`ONMC_LEARNING=0` stops durable memory inclusion while retaining the task's
explicit working state. Existing `supersedes` and `contradicts` edges are used
only when both endpoints are eligible and edge confidence is at least 0.8.
This is explicit relationship handling, not general semantic conflict detection.

## Budgets and storage

- Default packet budget: 6,000 characters, configurable from 1,000 to 32,000.
- Goal and pinned constraints remain whole. A budget that cannot hold them is
  rejected. Optional notes/memories are included whole or omitted with reasons.
- Token counts are estimates (`UTF-8 bytes / 4`), not tokenizer guarantees.
- At most 80 retrieved candidates, 16 active files, and 32 working notes per
  session. Older notes retire with a visible count. Each new next step replaces
  the previous one.
- Goals and focus prompts are limited to 4,000 characters; individual constraints
  to 2,000. Over-limit hook input produces an unavailable-context notice. Use a
  concise task description or explicitly start that session with a shorter goal.
- At most 64 distinct files are hashed per compilation, at most 2 MiB per file.
  Hashes and initial Git lookups are reused within the packet. Initial Git checks
  have a 1.5-second time allowance; uncertain sources remain excluded.
- State lives in the existing local `.onmc` SQLite database. Atomic transactions
  prevent concurrent hooks from losing note updates. No model calls, external
  service, telemetry upload, or extra storage backend is needed.
- Working state is not included in `.agent-memory` exports and is not
  automatically promoted to durable memory.

```bash
onmc working status --session SESSION_ID --json
onmc working disable
```

Disable stops adaptive injection; it preserves stored state and other ONMC
hooks. Hook errors remain nonblocking and report degraded context instead of
silently falling back to stale recall.

Legacy automatic `CLAUDE.md` refresh also preserves authored instructions. ONMC
records the digest of files it generates and automatically refreshes an existing
file only while its contents still match that digest. Manual edits, symlinks, and
older metadata without an ownership digest prevent automatic replacement. A file
changed while generation is running is preserved too; this is not an atomic lock
against arbitrary concurrent editors. Explicit `onmc claude-md generate` and
`onmc claude-md update` remain intentional write operations. Preview first with
`onmc claude-md preview --no-llm` when reviewing existing guidance.
Because `update` can retain user-written sections, its output is conservatively
excluded from automatic whole-file refresh; explicit `generate` establishes
ownership of the complete generated file.

## Reproduce the demonstration

```bash
python scripts/demo-working-context.py --output /tmp/working-context-demo.json
pytest tests/test_working_context.py tests/test_working_context_integration.py
```

The demo uses real temporary Git files, SQLite, and the prompt hook dispatcher.
It recalls a 30-second TTL, edits the source to 60 seconds while retaining the
same file timestamp, then checks withdrawal, repeat suppression, constraint
restoration, session isolation, and packet budgets. Output distinguishes checks
from observed local timing. It performs no model calls and does not measure
Claude task success or claim a quality/cost improvement over native Claude.

For a reproducible scale/ablation benchmark and paired Codex coding pilot, see
the [benchmark protocol and results](benchmarks/working-context.md). Component
checks, context delivery savings, and externally graded coding success are
reported separately.

Instructions remain advisory. ONMC cannot erase text already in Claude's
conversation, inspect its hidden context, guarantee instruction adherence, or
control its compaction algorithm. It sends an explicit replacement packet and
withdrawal notice; file identity establishes freshness, not correctness.
Delivery is best-effort: a hook process can fail after recording delivery but
before Claude receives stdout. Resume/compaction forces a fresh packet, and the
MCP context tool can explicitly request one. Exactly-once delivery is not claimed.
