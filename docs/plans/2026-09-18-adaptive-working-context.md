# Adaptive working context

## Outcome

Keep the current coding task coherent across prompts, edits, and compaction.
ONMC maintains an explicit goal, pinned constraints, decisions, hypotheses, and
next steps for each agent session. It supplies a bounded, inspectable context
packet and withdraws recalled evidence when its source changes.

This implements the selected hero feature, adaptive working context. It does
not implement the separately discussed backend flight simulator.

## Architecture

- Reuse the existing SQLite database, memory retrieval, promotion policy, and
  Claude hook/MCP surfaces. No hosted service, model calls, or new dependencies.
- Store versioned working state in namespaced SQLite metadata with transactional
  read/modify/write. Key by the actual session ID; never infer a shared session.
- Preserve the initial goal until explicitly replaced. Prompts change current
  focus. User-configured constraints are copied into the session and survive
  compaction. Agent notes are labeled decisions/hypotheses/next steps, not facts.
- Recheck file content hashes when compiling context. Bind anchors to both the
  memory contents and source files. Uncommitted changes, deletion, revision,
  unsafe anchors, quarantine, and explicit conflicts can exclude a memory.
- Use bounded existing retrieval queries; reuse explicit supersedes/contradicts
  edges. Do not claim arbitrary natural-language contradiction detection.
- Keep goal and constraints whole. Reject a budget too small for mandatory
  state; never silently truncate a constraint. Pack complete optional items.
- Emit a new bounded packet only when delivery contents change; force full
  restoration on resume/compaction. Include withdrawal notices for previously
  supplied memories. Hooks cannot erase old model context.
- Feature is opt-in. Disabled and uninitialized projects keep existing behavior.
  Hook errors remain nonblocking and diagnostics stay off stdout.

## Tasks and acceptance

### 1. Session state and freshness (root)

- [x] Persist/reload isolated goals, constraints, notes, and bounded active files.
- [x] Serialize concurrent updates without lost notes; reject malformed state.
- [x] Detect dirty edits, deleted sources, unsafe paths, and memory revisions.
- [x] Explicit source acknowledgement records freshness without promoting memory.

Verification: focused unit tests using real SQLite and temporary Git repositories.

### 2. Adaptive compiler (root; depends on 1)

- [x] Retrieve bounded relevant candidates from existing memory search.
- [x] Apply promotion, learning kill switch, freshness, conflict, and budget gates.
- [x] Explain inclusions/exclusions, withdraw changed evidence, suppress duplicates.
- [x] Rehydrate constraints after simulated compaction, with no cross-session leak.

Verification: packet invariants, Unicode budgets, stale/contradictory/quarantined
memory tests, and replay of the same working session before/after source edits.

### 3. Agent integrations (parallel agent; depends on API from 1)

- [x] Add `onmc working` enable/start/context/note/status/disable/verify-memory.
- [x] Integrate actual session/cwd hook delivery before edits, after tools, on
  prompts, and on session restore. Keep plugin and local hook paths aligned.
- [x] Expose bounded working-context operations through MCP; preserve constraints
  on existing sessions and existing tool contracts.

Verification: CLI and hook JSON integration tests, enable/disable, malformed
payload, actual session identity, differing cwd, MCP behavior.

### 4. Product documentation and demonstration (root; depends on 2–3)

- [x] Document setup, real workflow, freshness acknowledgement, and limits.
- [x] Add a reproducible local demonstration with machine-readable results.
- [x] Update README/changelog and regenerate CLI reference using pinned Typer.

Verification: execute documented workflow against real files and SQLite; inspect
before/after context, repeat suppression, and compact/resume constraints.

### 5. Verify and ship (root; depends on all)

- [ ] Focused tests and independent change review.
- [ ] Full repository quality gate: Ruff, strict mypy, pytest with >=80% coverage,
  CLI reference check, wheel/sdist build, Twine metadata check.
- [ ] Recheck origin/main, commit only this feature, push directly to main as
  requested, and inspect CI for the exact published commit.

## Boundaries and risks

Content identity proves freshness relative to an observed version, not semantic
truth. Initially dirty or untracked sources need explicit acknowledgement.
Notes are not automatically promoted to durable memory. Whole-file hashes can
invalidate still-useful memories after unrelated edits; this favors visible
uncertainty. Context budgets are character budgets with labeled token estimates,
not provider-token guarantees. Instructions remain advisory: this feature cannot
guarantee an agent obeys them or control Claude's internal compaction.

The user authorized implementation and direct-main publication. The plan records
the concrete implementation scope; execution proceeds through verification.

## Validation notes

The 38 new core/integration tests pass locally. Independent review found and
corrected source-only retrieval misses, a full-graph scan, and an inaccurate
source-change label on hash-budget exhaustion. The eight-check Git/SQLite/hook
demo passes. A live Claude attempt stopped before a model call because OAuth
authentication expired; model quality and adherence remain unmeasured.

Disk exhaustion caused failures in the first broader local run. Only temporary
fixtures created by this task were removed. Final full-suite validation runs in
the repository CI on a staging branch before advancing main. Required gate
repairs also cover optional OpenTelemetry mypy imports and metadata 2.4 output
for the declared Twine 6 validator.
