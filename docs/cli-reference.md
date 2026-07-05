# CLI Reference

This file is generated from Typer help output.
Run `python scripts/generate-cli-reference.py` after changing CLI commands.

## `onmc`

```text
Usage: onmc [OPTIONS] COMMAND [ARGS]...

 Memory-grounded autonomous coding loops for Claude Code and Codex.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --install-completion          Install completion for the current shell.      │
│ --show-completion             Show completion for the current shell, to copy │
│                               it or customize the installation.              │
│ --help                        Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ tui             Open the interactive terminal brain-browser for memory       │
│                 curation.                                                    │
│ setup           Run the interactive ONMC onboarding wizard.                  │
│ init            Initialize ONMC state in the current git repository.         │
│ ingest          Ingest repo knowledge into local structured memory.          │
│ brief           Compile a task-specific context brief.                       │
│ why             Explain why a file looks the way it does, from memory + git  │
│                 history.                                                     │
│ onboard         Give a new dev (or agent) the guided five-minute repo tour   │
│                 from memory.                                                 │
│ blame           Git blame for knowledge: map a file's symbols to the         │
│                 memories that govern them.                                   │
│ coverage        Show a knowledge-gap dashboard: coverage % + uncovered       │
│                 hotspot files.                                               │
│ memory-diff     Show what repo knowledge changed between two commits.        │
│ digest          Show what the repo/team learned since a git ref.             │
│ guard           Surface recorded dead-ends so you never repeat a known       │
│                 failure.                                                     │
│ recall          Search memory for past incidents matching an error or        │
│                 stacktrace.                                                  │
│ reuse           Surface existing code that already does a thing — reuse      │
│                 before reimplementing.                                       │
│ ask             Ask a natural-language question answered from repo memory.   │
│ check           Flag staged/changed files that touch recorded invariants or  │
│                 dead-ends.                                                   │
│ ui              Open the local read-only ONMC visual dashboard.              │
│ status          Show local ONMC status.                                      │
│ statusline      Print a compact one-line brain health string for Claude Code │
│                 statusLine.                                                  │
│ hud             Display a rich multi-line memory health HUD panel.           │
│ report          Generate a shareable agent-readiness report.                 │
│ sync            Export, restore, or hook git-portable ONMC memory state.     │
│ pull            Import another repo's .agent-memory/ export into this brain  │
│                 (federated memories).                                        │
│ serve           Serve ONMC over the requested runtime protocol.              │
│ solve           Compile repo-aware context and ask the configured LLM for    │
│                 the next best approach.                                      │
│ review          Compile repo-aware review context and critique the proposed  │
│                 approach.                                                    │
│ teach           Compile repo-aware teaching context and generate a learning  │
│                 artifact.                                                    │
│ consolidate     Clean and strengthen the memory store (dedup, merge,         │
│                 promote/demote, edge graph).                                 │
│ mine            Mine Claude Code session transcripts into ONMC memory.       │
│ capture         Heuristically capture durable memory from a session          │
│                 transcript.                                                  │
│ doctor          Run a health check over repo state, memory, provider setup,  │
│                 and integrations.                                            │
│ audit           Scan agent configuration for security risks and emit a       │
│                 scored report.                                               │
│ preflight       Run the exact CI quality gate locally, in the same order CI  │
│                 runs it.                                                     │
│ verify-diff     Adversarially verify the working diff against a base ref.    │
│ bench           Measure whether onmc memory actually reduces wasted work.    │
│ savings         Show a shareable 'Memory Wrapped' token-ROI card.            │
│ evolution       Show the compounding-proof evolution card across             │
│                 loop/autopilot runs.                                         │
│ benchmark       Run a reproducible benchmark suite against the current repo  │
│                 brain.                                                       │
│ plug            Wire onmc into a target coding agent (one-shot idempotent    │
│                 wizard).                                                     │
│ feedback        Apply a human trust signal to a stored memory.               │
│ import          Import skills or memories from an external tool into the     │
│                 ONMC brain.                                                  │
│ loop            Run a memory-grounded autonomous loop that avoids recorded   │
│                 dead-ends.                                                   │
│ loop-templates  List available built-in loop templates.                      │
│ autopilot       Run the full KNOW→(PLAN)→ACT→PROVE→LEARN autopilot cycle on  │
│                 a goal.                                                      │
│ nomistakes      Run the No-Mistakes PR gate: audit + eval + autopilot +      │
│                 receipt verdict.                                             │
│ release         Draft the next release from conventional-commit history.     │
│ badge           Render a "No-Slop verified" proof-of-work badge from an onmc │
│                 receipt.                                                     │
│ fix-ci          Read a failed PR's CI log and emit a deterministic fix plan. │
│ flywheel        Mine verified run trajectories to recommend winning          │
│                 approaches.                                                  │
│ mission         Run the engineering pipeline end-to-end into one mission     │
│                 plan.                                                        │
│ missioncontrol  Live, read-only dashboard for an onmc swarm.                 │
│ nightshift      Plan a bounded, verified overnight swarm + preview the       │
│                 morning digest.                                              │
│ pack            Build a per-task context pack: dead-ends, decisions, reuse,  │
│                 files.                                                       │
│ registry-demo   Proof-of-concept command registered with zero edits to       │
│                 ``cli.py``.                                                  │
│ roast           Roast this repo's agent-readiness — a blunt 0-100 score +    │
│                 findings.                                                    │
│ route           Deterministically route a task to an                         │
│                 agent/model/strategy/gate.                                   │
│ sbom            Generate a CycloneDX 1.5 SBOM of this project's              │
│                 dependencies.                                                │
│ scorecard       One shareable agent-readiness + trust scorecard for this     │
│                 repo.                                                        │
│ session-search  Full-text search across all of onmc's persisted history.     │
│ timeline        Tell this repo's evolution story from its brain.             │
│ wrap            Make onmc the default layer for Claude Code in this repo.    │
│ unwrap          Remove the onmc wrap layer — the perfect inverse of ``onmc   │
│                 wrap``.                                                      │
│ memory          Inspect stored memory.                                       │
│ spec            Inspect and validate the Agent Memory open spec.             │
│ task            Manage task lifecycle state.                                 │
│ attempt         Track task-scoped attempts.                                  │
│ llm             Configure optional LLM providers.                            │
│ hooks           Install and run Claude Code compaction hooks.                │
│ claude-md       Generate and maintain CLAUDE.md from ONMC memory.            │
│ playbook        Synthesize and manage memory-derived playbooks.              │
│ skill           Manage self-improving skills synthesized from playbooks and  │
│                 memory patterns.                                             │
│ user            Manage cross-repo user preferences (stored in ~/.onmc, not   │
│                 repo-scoped).                                                │
│ profile         Show and rebuild the derived user behavioral profile         │
│                 (~/.onmc/user.db).                                           │
│ notify          Inspect and test the context firewall notification sink.     │
│ gh-aw           Scaffold memory-aware GitHub Actions agentic workflows.      │
│ mcp             MCP Trust Gateway — classify tool calls against a policy.    │
│ swarm           Parallel accountable agent loops — a bounded pool of         │
│                 run_loop workers. Honest: 'many tasks' = a queue drained by  │
│                 min(cpu-1, 8) workers, not unlimited simultaneous agents.    │
│ conventions     Capture and inherit the repo's coding conventions            │
│                 (.onmc/conventions.md).                                      │
│ claim           Coordinate file/path leases for parallel agents.             │
│ ledger          Agent-work accounting (cost / wall-time / success-rate /     │
│                 ROI) over the run receipts that onmc loop and swarm write.   │
│                 Honest: cost is n/a when a receipt did not report it — never │
│                 fabricated.                                                  │
│ fleet           Operator view for local agent fleets (swarm + claims +       │
│                 receipts).                                                   │
│ wiki            Generate wiki and knowledge-graph exports from stored        │
│                 memory.                                                      │
│ codegraph       Structural repo graph — tiny, smart context for agents.      │
│                 Deterministic, offline (stdlib ast only).                    │
│ trace           Agent Trace Observatory — instrument a session and get a     │
│                 token-ROI report.                                            │
│ eval            Measure and gate memory recall quality (offline,             │
│                 deterministic).                                              │
│ replay          Replay Lab — re-run a recorded session and produce a         │
│                 regression report.                                           │
│ arena           Model gladiator: head-to-head ELO scoreboard — record bouts  │
│                 between models and track their ratings over time.            │
│ attest          Verifiable, portable proof-of-work — turn a receipt into a   │
│                 signed attestation.                                          │
│ autoroute       Apply flywheel learning: recommend the historically-best     │
│                 model for a goal.                                            │
│ coach           Live hype/roast session commentator + streaks. Reacts to     │
│                 coding-session events with personality-driven quips and      │
│                 tracks your green/red streak.                                │
│ contract        Spec-as-contract: generate a failing test + stub from an     │
│                 interface spec.                                              │
│ crossrepo       Cross-repo brain: impact map + federated memory recall       │
│                 across sibling repos.                                        │
│ drift           Enforce institutional memory — flag CANDIDATE code           │
│                 violations of recorded decisions/invariants for review       │
│                 (heuristic, not a proof).                                    │
│ handoff         Package / resume portable cross-session task context.        │
│ inbox           Ranked work queue: manual adds + TODO/FIXME + coverage gaps  │
│                 + memory.                                                    │
│ leash           Guardrails-as-game: define session rules, check compliance,  │
│                 and score the agent.                                         │
│ membudget       Memory-budget guard: report store size, flag over-budget,    │
│                 suggest consolidations.                                      │
│ memguard        Memory-integrity firewall: scan memory entries for           │
│                 adversarial content.                                         │
│ memprovider     Manage and query external memory providers that augment      │
│                 onmc's built-in store (mem0, supermemory, builtin).          │
│                 Providers run alongside the built-in store — they never      │
│                 replace it.                                                  │
│ memstage        Write-approval staging queue: propose memory writes, review  │
│                 diffs, then approve or reject — nothing lands in the store   │
│                 without your sign-off.                                       │
│ orggraph        Institutional-memory knowledge graph — entities, typed       │
│                 edges, lineage.                                              │
│ proptest        Generate property/invariant tests for pure functions.        │
│ proxy           OpenAI-compatible local proxy for onmc's configured LLM      │
│                 provider.                                                    │
│ quest           Gamified RPG backlog: XP from verified runs, levels, bosses, │
│                 loot.                                                        │
│ registry        Agent reputation trust ledger — aggregate signed             │
│                 attestations into a queryable, rankable track record.        │
│ selfimprove     After-turn learning review -- extract durable learnings from │
│                 a transcript and propose memory updates for human approval.  │
│ skillguard      Skill write-approval gate: propose skill create/edit/delete, │
│                 review diffs, then approve or reject — nothing lands in the  │
│                 skill store without your sign-off.                           │
│ twin            Rehearse a code change offline: predict blast radius,        │
│                 surface covering tests, flag high-risk touches. Analysis     │
│                 only — never runs or edits code.                             │
│ viz             Render onmc graphs as shareable diagrams (Mermaid or D2, no  │
│                 server, no dep).                                             │
│ whip            Steer a running agent and record reward signals (the reins + │
│                 whip control surface).                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc arena`

```text
Usage: onmc arena [OPTIONS] COMMAND [ARGS]...

 Model gladiator: head-to-head ELO scoreboard — record bouts between models and
 track their ratings over time.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ bout         Record a head-to-head bout result and update ELO ratings.       │
│ leaderboard  Show the ELO leaderboard — models ranked by rating.             │
│ standings    Show one model's ELO record + rating history.                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc arena bout`

```text
Usage: onmc arena bout [OPTIONS] MODEL_A MODEL_B

 Record a head-to-head bout result and update ELO ratings.

 MODEL_A and MODEL_B are model names (e.g. ``gpt-4o``, ``claude-3-7``).
 ``--winner`` must be ``A``, ``B``, or ``draw``.

 The bout is appended to ``.onmc/arena/bouts.jsonl`` and ratings are
 recomputed from scratch via the deterministic ELO formula, then
 snapshotted to ``.onmc/arena/ratings.json``.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    model_a      TEXT  Name / identifier of the first model. [required]     │
│ *    model_b      TEXT  Name / identifier of the second model. [required]    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --winner        TEXT  Bout outcome: A (model_a won), B (model_b won), or  │
│                          draw.                                               │
│                          [required]                                          │
│    --task          TEXT  Optional free-text task description for context.    │
│    --json                Emit the updated ratings as JSON.                   │
│    --help                Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc arena leaderboard`

```text
Usage: onmc arena leaderboard [OPTIONS]

 Show the ELO leaderboard — models ranked by rating.

 Ratings are recomputed from the persisted bouts log on every call so
 they always reflect the deterministic ELO formula.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the leaderboard as JSON.                                │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc arena standings`

```text
Usage: onmc arena standings [OPTIONS] MODEL

 Show one model's ELO record + rating history.

 Exits non-zero when the model has no bouts recorded.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    model      TEXT  The model name to look up. [required]                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the model's standings as JSON.                          │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc ask`

```text
Usage: onmc ask [OPTIONS] QUESTION

 Ask a natural-language question answered from repo memory.

 Returns the most relevant memories with citations.  When an LLM provider
 is configured, also synthesizes a concise answer grounded in those memories.
 Ranking and citations always work offline — synthesis is best-effort and
 its failure never breaks the command.

 Examples:

   onmc ask "why do we avoid bypassing the cache boundary?"

   onmc ask "what failed when we tried to use X?" --no-synth

   onmc ask "what is the auth decision?" --json

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    question      TEXT  Natural-language question to answer from repo       │
│                          memory.                                             │
│                          [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --limit           INTEGER RANGE [x>=1]  Maximum number of memory entries to  │
│                                         rank.                                │
│                                         [default: 8]                         │
│ --json                                  Emit result as JSON.                 │
│ --no-synth                              Skip LLM synthesis and return ranked │
│                                         entries only.                        │
│ --help                                  Show this message and exit.          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc attempt`

```text
Usage: onmc attempt [OPTIONS] COMMAND [ARGS]...

 Track task-scoped attempts.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ add     Add an attempt record for a task.                                    │
│ list    List attempts attached to a task.                                    │
│ show    Show one attempt record.                                             │
│ update  Update an existing attempt.                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc attempt add`

```text
Usage: onmc attempt add [OPTIONS] TASK_ID

 Add an attempt record for a task.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    task_id      TEXT  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --summary                  TEXT                    Short attempt summary. │
│                                                       [required]             │
│ *  --kind                     [fix_attempt|investiga  Attempt kind.          │
│                               tion|test_strategy|ref  [required]             │
│                               actor_attempt|other]                           │
│ *  --status                   [proposed|tried|reject  Attempt status.        │
│                               ed|succeeded|partial]   [required]             │
│    --reasoning-summary        TEXT                    Why this attempt       │
│                                                       seemed worth trying.   │
│    --evidence-for             TEXT                    Signals supporting the │
│                                                       attempt.               │
│    --evidence-against         TEXT                    Signals against the    │
│                                                       attempt.               │
│    --file                     TEXT                    Repeat to record       │
│                                                       touched file paths.    │
│    --help                                             Show this message and  │
│                                                       exit.                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc attempt list`

```text
Usage: onmc attempt list [OPTIONS] TASK_ID

 List attempts attached to a task.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    task_id      TEXT  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc attempt show`

```text
Usage: onmc attempt show [OPTIONS] ATTEMPT_ID

 Show one attempt record.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    attempt_id      TEXT  [required]                                        │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc attempt update`

```text
Usage: onmc attempt update [OPTIONS] ATTEMPT_ID

 Update an existing attempt.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    attempt_id      TEXT  [required]                                        │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --status                   [proposed|tried|rejec  Updated attempt status. │
│                               ted|succeeded|partial  [required]              │
│                               ]                                              │
│    --summary                  TEXT                   Replace the attempt     │
│                                                      summary.                │
│    --reasoning-summary        TEXT                   Update reasoning notes. │
│    --evidence-for             TEXT                   Update supporting       │
│                                                      evidence.               │
│    --evidence-against         TEXT                   Update                  │
│                                                      counter-evidence.       │
│    --file                     TEXT                   Replace touched file    │
│                                                      paths.                  │
│    --help                                            Show this message and   │
│                                                      exit.                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc attest`

```text
Usage: onmc attest [OPTIONS] COMMAND [ARGS]...

 Verifiable, portable proof-of-work — turn a receipt into a signed attestation.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ sign        Build a signed, portable attestation from an onmc receipt.       │
│ verify      Verify an attestation file; exit 0 when valid, 1 when not.       │
│ reputation  Summarise this repo's agent track record from all receipts.      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc attest reputation`

```text
Usage: onmc attest reputation [OPTIONS]

 Summarise this repo's agent track record from all receipts.

 Scans ``.agent-memory/receipts/`` and folds every run into a portable
 reputation summary: total runs, how many are attestable, verified-rate,
 distinct goals, and the time span — the shape an ERC-8004 reputation
 registry would consume.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the reputation summary as JSON.                         │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc attest sign`

```text
Usage: onmc attest sign [OPTIONS] RECEIPT_OR_SWARM_ID

 Build a signed, portable attestation from an onmc receipt.

 Distils the receipt into a minimal verifiable claim (subject, goal,
 tamper-evidence hashes, verified flag, timestamp) and signs it. With a
 secret (``--secret`` or ``ONMC_ATTEST_SECRET``) the signature is an
 HMAC-SHA256; without one it is a SHA256 integrity digest, clearly marked
 unsigned. ``--json`` emits the attestation for a verifier or registry.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    receipt_or_swarm_id      TEXT  Path to a receipt JSON, or a swarm id    │
│                                     (resolved via its manifest).             │
│                                     [required]                               │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --unit          TEXT  Unit id to select when a swarm id is given.            │
│ --secret        TEXT  Shared secret for HMAC signing (else                   │
│                       ONMC_ATTEST_SECRET, else unsigned).                    │
│ --json                Emit the attestation as JSON.                          │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc attest verify`

```text
Usage: onmc attest verify [OPTIONS] FILE

 Verify an attestation file; exit 0 when valid, 1 when not.

 Recomputes the signature over the embedded claim and compares it in
 constant time. A signed attestation only passes with the correct secret;
 an unsigned one passes on its integrity digest alone.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    file      TEXT  Path to an attestation JSON produced by `attest sign    │
│                      --json`.                                                │
│                      [required]                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --secret        TEXT  Shared secret for HMAC verification (else              │
│                       ONMC_ATTEST_SECRET).                                   │
│ --json                Emit the verify result as JSON.                        │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc audit`

```text
Usage: onmc audit [OPTIONS] [PATH]

 Scan agent configuration for security risks and emit a scored report.

 Scans CLAUDE.md, AGENTS.md, .claude/settings.json,
 .claude/settings.local.json,
 .mcp.json, and hooks/ for secrets, over-broad permissions, hook injection
 vectors, and prompt-injection surfaces.

 Exit codes:

 - 0 — no findings at or above ``--fail-on`` threshold
 - 1 — one or more findings at or above the threshold  (CI gate)
 - 2 — usage error

 Use ``--fail-on critical`` for a lenient CI gate, ``--fail-on medium`` for
 a stricter one.

 Output formats:

 - ``text`` (default) — Rich-rendered scorecard in the terminal.
 - ``json`` — Full AuditReport serialised as JSON (same as legacy ``--json``).
 - ``sarif`` — SARIF 2.1.0 document for GitHub code-scanning, VS Code SARIF
   viewer, and other SAST integrations.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   [path]      PATH  Repo root to scan.  Defaults to the current directory.   │
│                     The directory does not need to be an initialised ONMC    │
│                     repo — audit is purely static.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                               Emit the full AuditReport as JSON to    │
│                                      stdout.                                 │
│ --format                       TEXT  Output format.  One of: text (default   │
│                                      Rich scorecard), json (AuditReport      │
│                                      JSON), sarif (SARIF 2.1.0 for GitHub    │
│                                      code-scanning and VS Code SARIF         │
│                                      viewer).  When --format is given it     │
│                                      takes precedence over the legacy --json │
│                                      flag.                                   │
│                                      [default: text]                         │
│ --fail-on                      TEXT  Exit non-zero when at least one finding │
│                                      at this severity or higher exists.  One │
│                                      of: critical, high, medium, low, info.  │
│                                      Default: high.                          │
│                                      [default: high]                         │
│ --semgrep     --no-semgrep           Also run semgrep static analysis and    │
│                                      fold its findings into the report.      │
│                                      Requires the 'semgrep' binary on PATH.  │
│                                      When the binary is absent this flag is  │
│                                      silently ignored — no pip dependency is │
│                                      added.  Default: off.                   │
│                                      [default: no-semgrep]                   │
│ --gitleaks    --no-gitleaks          Also run gitleaks secret scanning and   │
│                                      fold detected secrets into the report.  │
│                                      Requires the 'gitleaks' binary on PATH. │
│                                      When the binary is absent this flag is  │
│                                      silently ignored — no pip dependency is │
│                                      added.  Default: off.                   │
│                                      [default: no-gitleaks]                  │
│ --osv         --no-osv               Also run osv-scanner                    │
│                                      dependency-vulnerability scanning and   │
│                                      fold detected CVEs into the report.     │
│                                      Requires the 'osv-scanner' binary on    │
│                                      PATH.  When the binary is absent this   │
│                                      flag is silently ignored — no pip       │
│                                      dependency is added.  Default: off.     │
│                                      [default: no-osv]                       │
│ --help                               Show this message and exit.             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc autopilot`

```text
Usage: onmc autopilot [OPTIONS] GOAL

 Run the full KNOW→(PLAN)→ACT→PROVE→LEARN autopilot cycle on a goal.

 Orchestrates every onmc command in one narrated run:


 🧠 KNOW  — compile_brief + guard (dead-ends) + user_profile (preferences).
 📋 PLAN  — optional; --plan-with <model> runs an expensive planning pass
 first.
 ⚙ ACT   — memory-grounded autonomous loop (avoids recorded dead-ends).
 ✅ PROVE  — receipt + verified/not-verified verdict + cost.
 📈 LEARN  — capture session memory + skill_promote + consolidate.

 Ends with a "Your brain grew" delta (+N memories · +N skills · N dead-ends).


 Examples
 --------
 onmc autopilot "fix the cache invalidation bug"
 onmc autopilot "add rate limiting" --verify "pytest tests/" --max-cost-usd
 2.00
 onmc autopilot "refactor auth module" --dry-run   # KNOW only, no spend
 onmc autopilot "fix flaky test" --agent codex --max-iterations 5
 onmc autopilot "fix flaky test" --agent opencode --max-iterations 5
 onmc autopilot "fix bug" --json                   # machine-readable output
 onmc autopilot "add feature" --plan-with claude-opus-4-5 --execute-with
 claude-haiku-4-5
 onmc autopilot "fix CI" --isolate                  # safe worktree run

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    goal      TEXT  Goal for the autopilot run. [required]                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --agent                               TEXT                Agent CLI to use:  │
│                                                           claude (default),  │
│                                                           codex, or          │
│                                                           opencode.          │
│                                                           [default: claude]  │
│ --dry-run                                                 Run only the KNOW  │
│                                                           phase (compile     │
│                                                           brief, guard,      │
│                                                           profile) without   │
│                                                           invoking any agent │
│                                                           or verify          │
│                                                           subprocess.  No    │
│                                                           spend, no memory   │
│                                                           writes.            │
│ --max-iterations                      INTEGER RANGE       Maximum loop       │
│                                       [x>=1]              iterations.        │
│                                                           [default: 10]      │
│ --budget-tokens                       INTEGER RANGE       Stop when total    │
│                                       [x>=1]              tokens exceed this │
│                                                           budget.            │
│ --max-cost-usd                        FLOAT RANGE         Stop before the    │
│                                       [x>=0.0]            next iteration     │
│                                                           when cumulative    │
│                                                           cost (USD) exceeds │
│                                                           this value.        │
│ --max-wall-seconds                    INTEGER RANGE       Stop before the    │
│                                       [x>=1]              next iteration     │
│                                                           when elapsed       │
│                                                           wall-clock seconds │
│                                                           exceed this.       │
│ --verify                              TEXT                Shell command run  │
│                                                           after each         │
│                                                           iteration to       │
│                                                           verify success.    │
│                                                           [default: pytest]  │
│ --plan-with                           TEXT                Model name for the │
│                                                           PLAN step          │
│                                                           (expensive model). │
│                                                           When set, a        │
│                                                           planning pass runs │
│                                                           before ACT: the    │
│                                                           model produces a   │
│                                                           precise            │
│                                                           implementation     │
│                                                           plan that is       │
│                                                           injected into the  │
│                                                           ACT goal and       │
│                                                           recorded as a      │
│                                                           memory.  Example:  │
│                                                           --plan-with        │
│                                                           claude-opus-4-5    │
│ --execute-with                        TEXT                Model name for the │
│                                                           ACT (execute) step │
│                                                           (cheap model).     │
│                                                           When set, the loop │
│                                                           runs with this     │
│                                                           model instead of   │
│                                                           the agent default. │
│                                                           Example:           │
│                                                           --execute-with     │
│                                                           claude-haiku-4-5   │
│ --isolate             --no-isolate                        Run ACT inside a   │
│                                                           fresh git worktree │
│                                                           and keep it only   │
│                                                           on success.        │
│                                                           Default off for    │
│                                                           backward           │
│                                                           compatibility.     │
│                                                           [default:          │
│                                                           no-isolate]        │
│ --json                                                    Print the full     │
│                                                           result as JSON.    │
│ --help                                                    Show this message  │
│                                                           and exit.          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc autoroute`

```text
Usage: onmc autoroute [OPTIONS] COMMAND [ARGS]...

 Apply flywheel learning: recommend the historically-best model for a goal.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ suggest  Recommend the historically-best model for GOAL from verified        │
│          receipts.                                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc autoroute suggest`

```text
Usage: onmc autoroute suggest [OPTIONS] GOAL

 Recommend the historically-best model for GOAL from verified receipts.

 Deterministic and offline: reuses the flywheel's learned per-goal-keyword
 and overall verified-outcome stats to pick a model, with an honest
 confidence and basis.  With no receipts it returns the default model at
 confidence 0 (exit 0) — never fabricates a recommendation.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    goal      TEXT  The goal/task to recommend a model for. [required]      │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --default        TEXT  Model to fall back to when history is thin.           │
│                        [default: sonnet]                                     │
│ --json                 Emit the suggestion as JSON.                          │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc badge`

```text
Usage: onmc badge [OPTIONS] RECEIPT_OR_SWARM_ID

 Render a "No-Slop verified" proof-of-work badge from an onmc receipt.

 onmc's swarm/loop receipts already prove work is real + verified
 (``git_tree_sha``, ``diff_sha``, ``verified``, ``receipt_hash``). This
 turns one receipt into a shareable shields.io badge: pass a receipt path
 or a swarm id (``--unit`` to pick a unit).

 With no flags, prints the Markdown badge + PR-comment body. ``--json``
 emits the shields.io endpoint payload. ``--post N`` publishes the comment
 on PR #N via ``gh``.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    receipt_or_swarm_id      TEXT  Path to a receipt JSON, or a swarm id    │
│                                     (resolved via its manifest).             │
│                                     [required]                               │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --unit        TEXT     Unit id to select when a swarm id is given.           │
│ --json                 Emit the shields.io endpoint payload as JSON.         │
│ --post        INTEGER  PR number to post the proof-of-work comment to (via   │
│                        gh pr comment).                                       │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc bench`

```text
Usage: onmc bench [OPTIONS]

 Measure whether onmc memory actually reduces wasted work.

 Runs a deterministic proof harness comparing two conditions: without onmc
 memory vs with onmc memory (brief/recall injected).  Default uses a
 built-in synthetic scenario that works on any repo with no init needed.

 The harness is a deterministic simulation — no LLM is called.  Results are
 reproducible in CI.  See the bench/harness.py module docstring for the full
 methodology.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --repo-memory          Run against the current repo's real memory store      │
│                        instead of built-in scenario.                         │
│ --json                 Print machine-readable JSON summary to stdout.        │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc benchmark`

```text
Usage: onmc benchmark [OPTIONS]

 Run a reproducible benchmark suite against the current repo brain.

 Measures five benchmarks — each labelled MEASURED (live, reproducible) or
 SIM (deterministic model, no LLM):


 MEASURED:
   1. recall_latency      — compile_recall p50/p95 ms + hits/query
   2. terse_vs_verbose    — mean % char reduction (title+citation vs markdown)
   3. toon_vs_json        — % char reduction (TOON vs compact JSON)
   4. brain_composition   — memory count + per-kind breakdown

 SIM (deterministic, identical across runs):
   5. harness_sim         — repeated-failure delta, wasted-attempts saved,
                            context-token % reduction, tasks-resolved delta

 Use --json for machine-readable output.  --runs controls timing precision.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --runs        INTEGER  Number of timing repetitions for timed benchmarks     │
│                        (default: 20).                                        │
│                        [default: 20]                                         │
│ --json                 Print machine-readable JSON to stdout.                │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc blame`

```text
Usage: onmc blame [OPTIONS] PATH

 Git blame for knowledge: map a file's symbols to the memories that govern
 them.

 Shows which recorded decisions, invariants, hotspots, and gotchas apply to
 each top-level symbol / section of the file.  Memories that reference the
 file but don't name a specific symbol appear in a file-level bucket.

 Symbol extraction is heuristic (regex, not AST) — results are approximate.
 Supported: .py, .ts, .tsx, .js, .jsx, .mjs, .cjs, .md, .mdx.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    path      TEXT  File path to blame (repo-relative or absolute).         │
│                      [required]                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --terse          Emit compact terse output (overrides ONMC_TERSE env var).   │
│ --help           Show this message and exit.                                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc brief`

```text
Usage: onmc brief [OPTIONS]

 Compile a task-specific context brief.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --task              TEXT                    Task description to compile a │
│                                                brief for.                    │
│                                                [required]                    │
│    --no-llm                                    Skip the optional LLM         │
│                                                reranking pass.               │
│    --style             [full|compact|caveman]  Brief rendering style.        │
│                                                [default: full]               │
│    --max-tokens        INTEGER RANGE [x>=1]    Trim markdown output to a     │
│                                                token budget.                 │
│    --stdout                                    Print markdown only,          │
│                                                optimized for agent paste     │
│                                                context.                      │
│    --terse                                     Emit compact terse output     │
│                                                (overrides ONMC_TERSE env     │
│                                                var).                         │
│    --help                                      Show this message and exit.   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc capture`

```text
Usage: onmc capture [OPTIONS]

 Heuristically capture durable memory from a session transcript.

 Extracts fixes, decisions, invariants, and notes from the session
 transcript without any LLM call.  Deduplicated entries are stored
 with source_type=session so they can be listed or pruned independently.

 Useful for on-demand re-capture or testing the auto-capture path that
 runs automatically on SessionEnd (set ONMC_AUTOCAPTURE=0 to disable).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --session           TEXT  Session ID to capture (default: most recent).      │
│ --transcript        PATH  Explicit path to a .jsonl transcript file.         │
│ --help                    Show this message and exit.                        │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc check`

```text
Usage: onmc check [OPTIONS]

 Flag staged/changed files that touch recorded invariants or dead-ends.

 By default checks all git-staged files (``git diff --cached --name-only``).
 Pass ``--file`` to check explicit paths.  Pass ``--base <ref>`` to diff
 against a git ref.

 Exit code is 0 by default (warn-only).  Pass ``--strict`` to exit nonzero
 when any warn-level findings are present.

 Pass ``--install-hook`` to wire this command as an idempotent git
 pre-commit hook (appends to any existing hook; never clobbers it).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --staged                    Check git-staged files (default).                │
│                             [default: True]                                  │
│ --file                TEXT  Explicit file paths to check (repeat for         │
│                             multiple).                                       │
│ --base                TEXT  Diff against this git ref instead of staged      │
│                             files.                                           │
│ --strict                    Exit nonzero when warn-level findings exist.     │
│ --install-hook              Install onmc check as a git pre-commit hook.     │
│ --help                      Show this message and exit.                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc claim`

```text
Usage: onmc claim [OPTIONS] COMMAND [ARGS]...

 Coordinate file/path leases for parallel agents.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ acquire  Acquire file/path leases for an owner.                              │
│ release  Release one path or all active paths for an owner.                  │
│ status   Show active path claims.                                            │
│ check    Check whether paths are free to claim.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc claim acquire`

```text
Usage: onmc claim acquire [OPTIONS] OWNER PATHS...

 Acquire file/path leases for an owner.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    owner         TEXT  Agent or process claiming the paths. [required]     │
│ *    paths...      TEXT  One or more file paths to claim. [required]         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --ttl-seconds        INTEGER RANGE [x>=1]  Lease duration in seconds.        │
│                                            [default: 3600]                   │
│ --json                                     Emit machine-readable JSON to     │
│                                            stdout.                           │
│ --help                                     Show this message and exit.       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc claim check`

```text
Usage: onmc claim check [OPTIONS] PATHS...

 Check whether paths are free to claim.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    paths...      TEXT  One or more file paths to check. [required]         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --owner        TEXT  Allow claims already held by this owner.                │
│ --json               Emit machine-readable JSON to stdout.                   │
│ --help               Show this message and exit.                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc claim release`

```text
Usage: onmc claim release [OPTIONS] OWNER

 Release one path or all active paths for an owner.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    owner      TEXT  Owner whose claim(s) should be released. [required]    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --path        TEXT  Release only this path for the owner.                    │
│ --json              Emit machine-readable JSON to stdout.                    │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc claim status`

```text
Usage: onmc claim status [OPTIONS]

 Show active path claims.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit machine-readable JSON to stdout.                        │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc claude-md`

```text
Usage: onmc claude-md [OPTIONS] COMMAND [ARGS]...

 Generate and maintain CLAUDE.md from ONMC memory.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --watch           Watch ONMC state and regenerate CLAUDE.md on updates.      │
│ --no-llm          Use deterministic generation only.                         │
│ --help            Show this message and exit.                                │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ generate  Generate CLAUDE.md from stored memory.                             │
│ update    Update stale CLAUDE.md sections.                                   │
│ preview   Preview CLAUDE.md without writing it.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc claude-md generate`

```text
Usage: onmc claude-md generate [OPTIONS]

 Generate CLAUDE.md from stored memory.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --no-llm          Use deterministic generation only.                         │
│ --help            Show this message and exit.                                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc claude-md preview`

```text
Usage: onmc claude-md preview [OPTIONS]

 Preview CLAUDE.md without writing it.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --no-llm          Use deterministic generation only.                         │
│ --help            Show this message and exit.                                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc claude-md update`

```text
Usage: onmc claude-md update [OPTIONS]

 Update stale CLAUDE.md sections.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --no-llm          Use deterministic generation only.                         │
│ --help            Show this message and exit.                                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc coach`

```text
Usage: onmc coach [OPTIONS] COMMAND [ARGS]...

 Live hype/roast session commentator + streaks. Reacts to coding-session events
 with personality-driven quips and tracks your green/red streak.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ react   React to a coding-session event with a quip + updated streak.        │
│ streak  Show the current streak, best streak, combo meter, and recent        │
│         events.                                                              │
│ cheer   A random-but-deterministic pep line seeded from your event count.    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc coach cheer`

```text
Usage: onmc coach cheer [OPTIONS]

 A random-but-deterministic pep line seeded from your event count.

 The same event count always yields the same pep line — fully reproducible,
 no wallclock, no random module.

 Examples:

     onmc coach cheer

     onmc coach cheer --json

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the cheer as JSON.                                      │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc coach react`

```text
Usage: onmc coach react [OPTIONS] EVENT

 React to a coding-session event with a quip + updated streak.

 The quip is deterministic: the same event, tone, and current event count
 always produce the same line.  Streak state is persisted across calls in
 ``.onmc/coach/streak.json``.

 Examples:

     onmc coach react test_pass

     onmc coach react pr_merged --tone roast

     onmc coach react build_break --tone dry --json

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    event      TEXT  Event kind to react to. Recognised: test_pass,         │
│                       test_fail, pr_merged, build_break, build_pass, commit, │
│                       revert, lint_pass, lint_fail, deploy_pass,             │
│                       deploy_fail, review_approved, review_rejected.         │
│                       [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --tone             [hype|roast|dry]  Commentary personality: hype, roast, or │
│                                      dry.                                    │
│                                      [default: hype]                         │
│ --from-file        FILE              Read the event kind from the last word  │
│                                      of the first line of FILE.              │
│ --json                               Emit the result as JSON.                │
│ --help                               Show this message and exit.             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc coach streak`

```text
Usage: onmc coach streak [OPTIONS]

 Show the current streak, best streak, combo meter, and recent events.

 Examples:

 onmc coach streak

 onmc coach streak --json

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit streak data as JSON.                                    │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc codegraph`

```text
Usage: onmc codegraph [OPTIONS] COMMAND [ARGS]...

 Structural repo graph — tiny, smart context for agents. Deterministic, offline
 (stdlib ast only).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ summary    Generate a compact markdown codegraph for token-efficient         │
│            navigation.                                                       │
│ build      Build the structural code graph and cache it to                   │
│            .onmc/codegraph.json.                                             │
│ neighbors  Show the blast radius (importers + dependents + tests) of a file  │
│            or symbol.                                                        │
│ context    Select a small, bounded set of files relevant to a goal.          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc codegraph build`

```text
Usage: onmc codegraph build [OPTIONS]

 Build the structural code graph and cache it to .onmc/codegraph.json.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the built graph as JSON.                                │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc codegraph context`

```text
Usage: onmc codegraph context [OPTIONS] GOAL

 Select a small, bounded set of files relevant to a goal.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    goal      TEXT  Goal or task description to select relevant files for.  │
│                      [required]                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --budget        INTEGER RANGE [x>=1]  Maximum number of files to return.     │
│                                       [default: 8]                           │
│ --json                                Emit the selection as JSON.            │
│ --help                                Show this message and exit.            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc codegraph neighbors`

```text
Usage: onmc codegraph neighbors [OPTIONS] TARGET

 Show the blast radius (importers + dependents + tests) of a file or symbol.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    target      TEXT  File path or symbol name to compute the blast radius  │
│                        for.                                                  │
│                        [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit neighbors as JSON.                                      │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc codegraph summary`

```text
Usage: onmc codegraph summary [OPTIONS]

 Generate a compact markdown codegraph for token-efficient navigation.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --max-files          INTEGER RANGE [x>=1]  Maximum hot files to include.     │
│                                            [default: 40]                     │
│ --max-dirs           INTEGER RANGE [x>=1]  Maximum directories to include.   │
│                                            [default: 12]                     │
│ --output     -o      PATH                  Write the markdown codegraph to   │
│                                            this path.                        │
│ --help                                     Show this message and exit.       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc consolidate`

```text
Usage: onmc consolidate [OPTIONS]

 Clean and strengthen the memory store (dedup, merge, promote/demote, edge
 graph).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --dry-run          Compute the consolidation plan without writing anything.  │
│ --help             Show this message and exit.                               │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc contract`

```text
Usage: onmc contract [OPTIONS] COMMAND [ARGS]...

 Spec-as-contract: generate a failing test + stub from an interface spec.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ init  Emit a failing pytest skeleton + a stub module from a contract spec.   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc contract init`

```text
Usage: onmc contract init [OPTIONS] SPEC

 Emit a failing pytest skeleton + a stub module from a contract spec.

 The generated test fails until the stub is implemented — TDD by
 construction. Re-running with the same spec is idempotent.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    spec      PATH  Path to the JSON contract spec file. [required]         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --out          PATH  Directory the test file is written under.               │
│                      [default: tests]                                        │
│ --force              Overwrite existing test/stub files.                     │
│ --json               Emit a machine-readable JSON result.                    │
│ --help               Show this message and exit.                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc conventions`

```text
Usage: onmc conventions [OPTIONS] COMMAND [ARGS]...

 Capture and inherit the repo's coding conventions (.onmc/conventions.md).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ capture  Detect the repo's coding conventions and write                      │
│          .onmc/conventions.md.                                               │
│ show     Print the repo's coding conventions for injection into spawned      │
│          agents.                                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc conventions capture`

```text
Usage: onmc conventions capture [OPTIONS]

 Detect the repo's coding conventions and write .onmc/conventions.md.

 Parses pyproject.toml ( line-length / select / target-version and
  strict) and attaches the fixed repo norms.  Deterministic and
 offline.  Idempotent: re-running is a no-op unless --force is passed.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --force          Overwrite an existing .onmc/conventions.md.                 │
│ --help           Show this message and exit.                                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc conventions show`

```text
Usage: onmc conventions show [OPTIONS]

 Print the repo's coding conventions for injection into spawned agents.

 Detects conventions on the fly (does not require a prior capture) and emits
 them as a table, or as JSON with --json.  Deterministic and offline.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the conventions as JSON for agent injection.            │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc coverage`

```text
Usage: onmc coverage [OPTIONS]

 Show a knowledge-gap dashboard: coverage % + uncovered hotspot files.

 Answers "which parts of this repo does the memory actually cover, and where
 are the blind spots?"  The killer feature is surfacing high-churn files that
 have zero memory coverage — those are the landmines most likely to cause
 regressions when touched without context.

 Pass --suggest to turn the gap dashboard into an actionable to-do list.
 Pass --apply to automatically create stub memory entries for each suggestion
 (idempotent — re-running skips entries that already exist).

 Requires at least one `onmc ingest` run (file stats must exist).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json             Emit the CoverageReport (and suggestions when --suggest)  │
│                    as JSON instead of the dashboard.                         │
│ --suggest          Print actionable documentation suggestions for each       │
│                    uncovered hotspot. Deterministic — no LLM required.       │
│ --apply            Create stub memory entries (confidence=0.2,               │
│                    tag=coverage-stub) for each suggestion that does not      │
│                    already exist. Implies --suggest. Idempotent: re-running  │
│                    skips stubs that already exist.                           │
│ --help             Show this message and exit.                               │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc crossrepo`

```text
Usage: onmc crossrepo [OPTIONS] COMMAND [ARGS]...

 Cross-repo brain: impact map + federated memory recall across sibling repos.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ scan    Map where a change in one repo ripples into its siblings.            │
│ recall  Search every repo's ``.agent-memory/`` export for a query,           │
│         attributed by repo.                                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc crossrepo recall`

```text
Usage: onmc crossrepo recall [OPTIONS] QUERY [PATHS]...

 Search every repo's ``.agent-memory/`` export for a query, attributed by repo.

 Loads each repo's memory export (skipping repos without one), ranks hits by
 deterministic token overlap, and reports the best matches with their source
 repo. Pass repos via ``--repo`` (repeatable) and/or positional paths.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    query           TEXT  Search query for federated memory recall.         │
│                            [required]                                        │
│      [paths]...      TEXT  Additional repo paths to search (positional).     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --repo  -r      TEXT  Repo path to search (repeatable).                      │
│ --json                Emit recall hits as JSON.                              │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc crossrepo scan`

```text
Usage: onmc crossrepo scan [OPTIONS] PATHS...

 Map where a change in one repo ripples into its siblings.

 Scans each repo's top-level module/package names and reports the modules
 shared across two or more repos — the ripple surface. Deterministic and
 offline: same repos always yield the same map.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    paths...      TEXT  Sibling repo paths to scan for the cross-repo       │
│                          impact map.                                         │
│                          [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the impact map as JSON.                                 │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc digest`

```text
Usage: onmc digest [OPTIONS]

 Show what the repo/team learned since a git ref.

 Produces a knowledge changelog grouped by kind (Decisions, Invariants,
 Gotchas, Failed Approaches, …) covering memories added or updated since
 *since*.

 Prefers committed ``.agent-memory/`` snapshots for precision; falls back to
 live ``created_at`` filtering when the committed export is absent at the
 given ref.

 The report is also written as a markdown artifact to ``.onmc/compiled/``.


 Examples:
   onmc digest --since v1.2.0
   onmc digest --since main
   onmc digest --since abc1234

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --since        TEXT  Git ref (tag, branch, commit hash) to diff knowledge │
│                         from.                                                │
│                         [required]                                           │
│    --json               Emit JSON instead of a rich terminal report.         │
│    --help               Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc doctor`

```text
Usage: onmc doctor [OPTIONS]

 Run a health check over repo state, memory, provider setup, and integrations.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc drift`

```text
Usage: onmc drift [OPTIONS] COMMAND [ARGS]...

 Enforce institutional memory — flag CANDIDATE code violations of recorded
 decisions/invariants for review (heuristic, not a proof).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ check  Scan code for CANDIDATE violations of recorded memory.                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc drift check`

```text
Usage: onmc drift check [OPTIONS]

 Scan code for CANDIDATE violations of recorded memory.

 For each decision/invariant/convention that carries a checkable
 directive ("never use X", "always use Y", "adopt Z", "prefer A over B"),
 scan the repo's Python files for contradicting evidence.  Findings are
 HEURISTIC candidates for human review — never a certainty. Deterministic
 and offline; degrades gracefully (empty brain → nothing to check).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                             Emit the drift report as  │
│                                                    JSON.                     │
│ --min-confidence        FLOAT RANGE [0.0<=x<=1.0]  Drop findings below this  │
│                                                    confidence (0.0-1.0).     │
│                                                    [default: 0.0]            │
│ --help                                             Show this message and     │
│                                                    exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc eval`

```text
Usage: onmc eval [OPTIONS] COMMAND [ARGS]...

 Measure and gate memory recall quality (offline, deterministic).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ create   Create a new eval case and persist it to .onmc/evals/<id>.json.     │
│ run      Run the eval suite and report memory recall quality.                │
│ compare  Compare with-memory vs without-memory eval scores.                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc eval compare`

```text
Usage: onmc eval compare [OPTIONS]

 Compare with-memory vs without-memory eval scores.

 Runs the suite twice and shows the delta.  A positive delta proves the brain
 is contributing.  Use --baseline to gate CI (exits 1 when score_delta <
 threshold).

 Examples:

   onmc eval compare

   onmc eval compare --baseline 10   # fail CI if brain contributes <10 points

   onmc eval compare --json          # machine-readable output

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                           Output comparison as JSON.  │
│ --baseline            FLOAT RANGE                Exit non-zero when the      │
│                       [0.0<=x<=100.0]            with-memory score delta     │
│                                                  (0–100) is below this       │
│                                                  value. Use in CI to gate on │
│                                                  brain contribution          │
│                                                  regression.                 │
│                                                  [default: 0.0]              │
│ --recall-limit        INTEGER                    Max recall entries per      │
│                                                  case.                       │
│                                                  [default: 8]                │
│ --help                                           Show this message and exit. │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc eval create`

```text
Usage: onmc eval create [OPTIONS]

 Create a new eval case and persist it to .onmc/evals/<id>.json.

 Two modes:

 --from-memory <id>   Derive query + expectations from an existing memory
 entry.

 --query <text>       Manual mode: provide query + optional --expect-file /
 --expect-deadend.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --from-memory             TEXT  Derive eval case from existing memory ID.    │
│ --query           -q      TEXT  Query/task for the eval case (manual mode).  │
│ --id                      TEXT  Custom case ID (optional, auto-derived when  │
│                                 omitted).                                    │
│ --expect-file             TEXT  Expected file/memory ID to appear in recall  │
│                                 results. Repeatable: --expect-file foo       │
│                                 --expect-file bar                            │
│ --expect-deadend          TEXT  Substring expected in a guard dead-end       │
│                                 entry. Repeatable: --expect-deadend 'tried   │
│                                 X' --expect-deadend 'bad approach'           │
│ --note                    TEXT  Optional human-readable note about what this │
│                                 case tests.                                  │
│ --help                          Show this message and exit.                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc eval run`

```text
Usage: onmc eval run [OPTIONS]

 Run the eval suite and report memory recall quality.

 Loads all cases from .onmc/evals/ and scores them against the live brain.
 Use --fail-under to gate CI (exits 1 when pass_rate < threshold).

 Examples:

   onmc eval run

   onmc eval run --fail-under 80   # fail CI if <80% of cases pass

   onmc eval run --json            # machine-readable output

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                             Output results as JSON.   │
│ --fail-under            FLOAT RANGE                Exit non-zero when        │
│                         [0.0<=x<=100.0]            pass_rate (0–100) is      │
│                                                    below this threshold. Use │
│                                                    in CI to gate on memory   │
│                                                    quality regression.       │
│                                                    [default: 0.0]            │
│ --without-memory                                   Run the cold baseline     │
│                                                    (simulate no retrieval).  │
│                                                    Useful for delta          │
│                                                    comparison.               │
│ --recall-limit          INTEGER                    Max recall entries per    │
│                                                    case.                     │
│                                                    [default: 8]              │
│ --help                                             Show this message and     │
│                                                    exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc evolution`

```text
Usage: onmc evolution [OPTIONS]

 Show the compounding-proof evolution card across loop/autopilot runs.

 Reads all run receipts from ``.agent-memory/receipts/`` and computes
 trend metrics: cost delta, iterations-to-converge delta, and verified
 rate.  All numbers come from real receipt data — no simulation.

 Requires at least 2 completed loop/autopilot runs with receipts.  Run
 ``onmc loop`` or ``onmc autopilot`` to generate receipts first.

 Use ``--json`` for machine-readable output.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON to stdout.                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc feedback`

```text
Usage: onmc feedback [OPTIONS] MEMORY_ID DIRECTION

 Apply a human trust signal to a stored memory.

 Use 'up' when a recalled memory proved useful; use 'down' when it was
 wrong or misleading.  Positive feedback slows confidence decay so
 corroborated memories stay ranked higher for longer.  Negative feedback
 demotes but does not erase — the memory remains searchable at a lower
 rank.


 Examples
 --------
 onmc feedback mem_abc123 up
 onmc feedback mem_abc123 down --note "outdated after refactor"
 onmc feedback mem_abc123 up --json

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    memory_id      TEXT  Memory ID to apply feedback to. [required]         │
│ *    direction      TEXT  Trust signal: 'up' (useful) or 'down'              │
│                           (wrong/misleading).                                │
│                           [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --note        TEXT  Optional note appended to the memory details.            │
│ --json              Emit the updated memory as JSON instead of a rich panel. │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc fix-ci`

```text
Usage: onmc fix-ci [OPTIONS] PR

 Read a failed PR's CI log and emit a deterministic fix plan.

 Plan-only by default: this command never spawns an agent or runs a
 swarm. Use ``--log <file>`` to plan offline from a captured log; without
 it the log is fetched via ``gh run view --log-failed``.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    pr      TEXT  PR number or URL whose failed CI to plan a fix for.       │
│                    [required]                                                │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --log         PATH  Read the CI log from this file instead of fetching via   │
│                     gh (offline).                                            │
│ --json              Emit the fix plan as JSON.                               │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc fleet`

```text
Usage: onmc fleet [OPTIONS] COMMAND [ARGS]...

 Operator view for local agent fleets (swarm + claims + receipts).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ status  Summarize local swarm, claim, and receipt state.                     │
│ doctor  Diagnose stuck local fleet state.                                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc fleet doctor`

```text
Usage: onmc fleet doctor [OPTIONS]

 Diagnose stuck local fleet state.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON to stdout.                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc fleet status`

```text
Usage: onmc fleet status [OPTIONS]

 Summarize local swarm, claim, and receipt state.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --swarm-id        TEXT  Limit output to one swarm id.                        │
│ --json                  Print machine-readable JSON to stdout.               │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc flywheel`

```text
Usage: onmc flywheel [OPTIONS]

 Mine verified run trajectories to recommend winning approaches.

 Reads the tamper-evident run receipts written by ``onmc loop`` /
 ``onmc swarm``, aggregates them by model and goal keyword, and reports
 which approaches produced *verified* results — plus ranked
 recommendations. Deterministic and fully offline (no LLM call).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json               Emit the flywheel report as JSON.                       │
│ --since        TEXT  Only include runs since this time (e.g. 7d, 48h, or ISO │
│                      date).                                                  │
│ --help               Show this message and exit.                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc gh-aw`

```text
Usage: onmc gh-aw [OPTIONS] COMMAND [ARGS]...

 Scaffold memory-aware GitHub Actions agentic workflows.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ init  Scaffold memory-aware GitHub Actions workflows into a target repo.     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc gh-aw init`

```text
Usage: onmc gh-aw init [OPTIONS] [PATH]

 Scaffold memory-aware GitHub Actions workflows into a target repo.


 Generates four workflow files in .github/workflows/:
   onmc-issue-context.yml   — post memory context on new issues
   onmc-pr-preflight.yml    — blast-radius + memories + audit on PR open
   onmc-pr-learn.yml        — record merged PR outcome for future agents
   onmc-weekly-audit.yml    — weekly stale-memory audit via scheduled issue

 All writes are idempotent — re-running skips already-managed files unless
 --force is passed.  Use --dry-run to preview without writing anything.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   [path]      PATH  Target repo root. Defaults to the current directory (or  │
│                     nearest git root). The four workflows are written to     │
│                     PATH/.github/workflows/onmc-*.yml.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --dry-run          Show what would be written without writing anything.      │
│ --force            Overwrite existing onmc-managed workflow files.           │
│ --json             Output result as JSON.                                    │
│ --help             Show this message and exit.                               │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc guard`

```text
Usage: onmc guard [OPTIONS]

 Surface recorded dead-ends so you never repeat a known failure.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --task         TEXT                  Task description to check for        │
│                                         dead-ends.                           │
│                                         [required]                           │
│    --limit        INTEGER RANGE [x>=1]  Maximum number of dead-end entries   │
│                                         to return.                           │
│                                         [default: 8]                         │
│    --terse                              Emit compact terse output (overrides │
│                                         ONMC_TERSE env var).                 │
│    --help                               Show this message and exit.          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc handoff`

```text
Usage: onmc handoff [OPTIONS] COMMAND [ARGS]...

 Package / resume portable cross-session task context.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ create  Build a portable handoff bundle for GOAL and write it (or print it). │
│ resume  Read a handoff bundle FILE and render a resume briefing.             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc handoff create`

```text
Usage: onmc handoff create [OPTIONS] GOAL

 Build a portable handoff bundle for GOAL and write it (or print it).

 Assembles the context pack, goal-relevant decisions, recorded dead-ends,
 and recent run receipts into one JSON bundle. Missing sources degrade to
 empty sections with explanatory notes — the command never crashes.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    goal      TEXT  The task goal to package context for. [required]        │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --out         PATH  Where to write the bundle JSON.                          │
│ --json              Emit the bundle JSON to stdout instead of a file.        │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc handoff resume`

```text
Usage: onmc handoff resume [OPTIONS] FILE

 Read a handoff bundle FILE and render a resume briefing.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    file      PATH  Path to a handoff bundle JSON. [required]               │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the parsed bundle as JSON instead of a briefing.        │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc hooks`

```text
Usage: onmc hooks [OPTIONS] COMMAND [ARGS]...

 Install and run Claude Code compaction hooks.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ install         Install project-scoped Claude Code hooks into                │
│                 .claude/settings.json.                                       │
│ uninstall       Remove ONMC entries from project Claude Code settings and    │
│                 .mcp.json.                                                   │
│ status          Show current Claude hook installation and snapshot status.   │
│ pre-compact     Capture a compaction snapshot before Claude Code compacts    │
│                 context.                                                     │
│ session-start   Inject context at session start: boot digest on startup,     │
│                 continuation brief after compaction.                         │
│ prompt-recall   Inject the most relevant repo memories for the current user  │
│                 prompt.                                                      │
│ session-end     Run memory consolidation and heuristic auto-capture on       │
│                 SessionEnd.                                                  │
│ pre-tool-use    Inject file-level danger warnings before the agent edits a   │
│                 file.                                                        │
│ task-intercept  Intercept native ``Task`` agent-spawning and redirect it to  │
│                 ``onmc swarm``.                                              │
│ prompt-router   Route the user prompt through onmc and inject a "prefer onmc │
│                 paths" nudge.                                                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc hooks install`

```text
Usage: onmc hooks install [OPTIONS]

 Install project-scoped Claude Code hooks into .claude/settings.json.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --yes     -y        Accept defaults without prompting.                       │
│ --no-mcp            Skip MCP server setup.                                   │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc hooks post-compact`

```text
Usage: onmc hooks post-compact [OPTIONS]

 (deprecated)
 Deprecated alias for `onmc hooks session-start`.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc hooks pre-compact`

```text
Usage: onmc hooks pre-compact [OPTIONS]

 Capture a compaction snapshot before Claude Code compacts context.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc hooks pre-tool-use`

```text
Usage: onmc hooks pre-tool-use [OPTIONS]

 Inject file-level danger warnings before the agent edits a file.

 Called automatically by the Claude Code PreToolUse hook (matcher:
 ``Edit|Write|MultiEdit|NotebookEdit``).  Reads the hook payload from
 stdin, extracts ``tool_input.file_path``, looks up hotspot / invariant /
 failed-approach memories for that file, and emits a PreToolUse
 ``additionalContext`` JSON payload to stdout when anything notable is
 found.  Non-edit tools and unknown paths produce no output.

 Design invariants:
 - Always exits 0 — never blocks the edit.
 - Any exception is silently swallowed; stdout stays clean on error.
 - Output is tiny: at most a handful of bullet points.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc hooks prompt-recall`

```text
Usage: onmc hooks prompt-recall [OPTIONS]

 Inject the most relevant repo memories for the current user prompt.

 Reads the UserPromptSubmit JSON payload from stdin, extracts the ``prompt``
 field, searches stored memory for relevant entries, and writes the
 UserPromptSubmit additionalContext JSON to stdout.  Stdout is always pure
 JSON or empty — never mixed with diagnostics.  Always exits 0.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc hooks prompt-router`

```text
Usage: onmc hooks prompt-router [OPTIONS]

 Route the user prompt through onmc and inject a "prefer onmc paths" nudge.

 Installed by ``onmc wrap`` on the ``UserPromptSubmit`` hook. Reads the
 prompt from the stdin payload, routes it via the deterministic router +
 dead-end guard, and writes a terse ``additionalContext`` JSON payload.
 Stdout is always pure JSON or empty. Always exits 0; never raises.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc hooks session-end`

```text
Usage: onmc hooks session-end [OPTIONS]

 Run memory consolidation and heuristic auto-capture on SessionEnd.

 Called automatically by the Claude Code SessionEnd hook.  Reads the event
 payload from stdin (session_id, transcript_path, cwd, reason), runs a
 best-effort consolidation pass followed by heuristic auto-capture of
 durable memory from the just-ended session transcript.  Errors are
 swallowed; stdout is never written (SessionEnd hooks cannot inject
 context).

 Set ``ONMC_AUTOCAPTURE=0`` in the environment to disable auto-capture
 while keeping consolidation active.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc hooks session-start`

```text
Usage: onmc hooks session-start [OPTIONS]

 Inject context at session start: boot digest on startup, continuation brief
 after compaction.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc hooks status`

```text
Usage: onmc hooks status [OPTIONS]

 Show current Claude hook installation and snapshot status.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc hooks task-intercept`

```text
Usage: onmc hooks task-intercept [OPTIONS]

 Intercept native ``Task`` agent-spawning and redirect it to ``onmc swarm``.

 Installed by ``onmc wrap`` on the ``PreToolUse`` hook (matcher ``"Task"``).
 Reads the hook payload from stdin and emits either a ``deny`` decision
 (strict) redirecting the model to ``onmc swarm plan``, an
 ``additionalContext`` nudge (soft), or nothing (non-Task tool, or
 self-exemption when ``ONMC_ALLOW_TASK`` is set or an onmc swarm is active).

 Design invariants (identical to every onmc hook):
 - Always exits 0 — a wrapper that bricks Claude Code is unacceptable.
 - Any exception is swallowed; stdout stays clean (empty = allow) on error.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc hooks uninstall`

```text
Usage: onmc hooks uninstall [OPTIONS]

 Remove ONMC entries from project Claude Code settings and .mcp.json.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc hud`

```text
Usage: onmc hud [OPTIONS]

 Display a rich multi-line memory health HUD panel.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc import`

```text
Usage: onmc import [OPTIONS] SOURCE [PATH]

 Import skills or memories from an external tool into the ONMC brain.


 Sources
 -------
 omc       oh-my-claudecode skill files (.omc/skills/*.md).
           Auto-detects project (.omc/skills) then user (~/.omc/skills).
           Pass a path to override: onmc import omc /path/to/skills/

 hermes    Nous hermes-agent context files (MEMORY.md, USER.md).
           Auto-detects in the current directory.
           Pass a path to a file or directory to override.

 <path>    Generic .md file or directory of .md files.
           Imported as skills by default; pass --as memory to import
           each ## section as a separate memory entry.


 Idempotent
 ----------
 Re-importing the same files is safe: items already present in the store
 (matched by stable content-derived id) are counted as skipped, never
 duplicated.  Use --dry-run to preview without writing.


 Examples
 --------
 onmc import omc
 onmc import omc ~/.omc/skills
 onmc import hermes
 onmc import hermes ./MEMORY.md
 onmc import ./docs/how-tos/
 onmc import ./RUNBOOK.md --as memory
 onmc import omc --dry-run
 onmc import hermes --json

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    source      TEXT  Source to import from. Use 'omc' for oh-my-claudecode │
│                        skills, 'hermes' for Nous hermes-agent context files, │
│                        or a path to a .md file / directory.                  │
│                        [required]                                            │
│      [path]      PATH  Optional path override. For 'omc': path to            │
│                        .omc/skills dir. For 'hermes': path to MEMORY.md /    │
│                        USER.md / containing directory. For generic markdown: │
│                        the .md file or directory (use as 'source' instead).  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --dry-run              Parse and report without writing anything.            │
│ --as             TEXT  Import generic markdown as 'skill' (default) or       │
│                        'memory'.                                             │
│                        [default: skill]                                      │
│ --json                 Emit the result as JSON instead of a rich table.      │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc inbox`

```text
Usage: onmc inbox [OPTIONS] COMMAND [ARGS]...

 Ranked work queue: manual adds + TODO/FIXME + coverage gaps + memory.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ add   Add a manual work item to the inbox (idempotent on text).              │
│ list  List persisted manual items (insertion order, unranked).               │
│ rank  Show the full ranked queue (manual + TODO/FIXME + coverage + memory).  │
│ run   Emit a plan for the top N ranked items (no execution).                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc inbox add`

```text
Usage: onmc inbox add [OPTIONS] TEXT

 Add a manual work item to the inbox (idempotent on text).

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    text      TEXT  The task description to enqueue. [required]             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the stored item as JSON.                                │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc inbox list`

```text
Usage: onmc inbox list [OPTIONS]

 List persisted manual items (insertion order, unranked).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the manual items as JSON.                               │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc inbox rank`

```text
Usage: onmc inbox rank [OPTIONS]

 Show the full ranked queue (manual + TODO/FIXME + coverage + memory).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the ranked queue as JSON.                               │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc inbox run`

```text
Usage: onmc inbox run [OPTIONS]

 Emit a plan for the top N ranked items (no execution).

 ``run`` is intentionally side-effect-free: it surfaces *what* it would
 work on next, ranked, so a human or an outer loop can decide. It never
 spawns work itself.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --top         INTEGER RANGE [x>=1]  How many top-ranked items to plan.       │
│                                     [default: 3]                             │
│ --json                              Emit the plan as JSON.                   │
│ --help                              Show this message and exit.              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc ingest`

```text
Usage: onmc ingest [OPTIONS]

 Ingest repo knowledge into local structured memory.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --files                 Ingest only the file paths passed after this flag.   │
│ --install-hook          Install the ONMC incremental post-commit hook.       │
│ --no-llm                Skip the optional LLM extraction pass.               │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc init`

```text
Usage: onmc init [OPTIONS]

 Initialize ONMC state in the current git repository.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc leash`

```text
Usage: onmc leash [OPTIONS] COMMAND [ARGS]...

 Guardrails-as-game: define session rules, check compliance, and score the
 agent.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ add     Add a new guardrail rule to the leash.                               │
│ list    List all active guardrail rules.                                     │
│ remove  Remove a guardrail rule by its ID.                                   │
│ check   Evaluate an event or action text against the active rules.           │
│ score   Show the compliance score, streak, and grade.                        │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc leash add`

```text
Usage: onmc leash add [OPTIONS] RULE

 Add a new guardrail rule to the leash.

 The rule TEXT is used both as the human-readable description and as the
 match pattern.  Patterns are tried as regexes first; if the regex is
 invalid it falls back to case-insensitive substring matching.

 Severity controls what happens on a match:

 \b soft\b  — advisory; violations are reported but no buzz is emitted.

 \b hard\b  — triggers a buzz (``buzz: true`` in JSON output) to signal
 a serious guardrail breach.

 Examples:

     onmc leash add "no console.log"

     onmc leash add "TODO" --severity hard

     onmc leash add "rm -rf" --severity hard

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    rule      TEXT  The house rule to add. [required]                       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --severity        TEXT  Rule severity: 'soft' (advisory) or 'hard' (triggers │
│                         a buzz on violation).                                │
│                         [default: soft]                                      │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc leash check`

```text
Usage: onmc leash check [OPTIONS] EVENT

 Evaluate an event or action text against the active rules.

 Violations are reported with their rule id, severity, matched text, and
 whether a buzz is emitted (hard violations only).  The check event is
 recorded in the history ledger so ``onmc leash score`` can track the
 compliance trend.

 Examples:

     onmc leash check "I just ran rm -rf node_modules"

     onmc leash check "added a console.log for debugging" --json

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    event      TEXT  Event text or action description to evaluate.          │
│                       [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the result as a JSON envelope.                          │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc leash list`

```text
Usage: onmc leash list [OPTIONS]

 List all active guardrail rules.

 Examples:

 onmc leash list

 onmc leash list --json

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit rules as a JSON envelope.                               │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc leash remove`

```text
Usage: onmc leash remove [OPTIONS] RULE_ID

 Remove a guardrail rule by its ID.

 Use ``onmc leash list`` to find the rule ID.

 Examples:

     onmc leash remove rule_abc123

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    rule_id      TEXT  The rule ID to remove. [required]                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc leash score`

```text
Usage: onmc leash score [OPTIONS]

 Show the compliance score, streak, and grade.

 Compliance is computed from all ``onmc leash check`` events recorded in
 the current session.  A ``streak`` counts consecutive clean checks from
 the most recent event backwards.

 Grade thresholds: A (≥95%), B (≥80%), C (≥60%), D (≥40%), F (<40%).
 ``N/A`` when no checks have been recorded yet.

 Examples:

     onmc leash score

     onmc leash score --json

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the score as a JSON envelope.                           │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc ledger`

```text
Usage: onmc ledger [OPTIONS] COMMAND [ARGS]...

 Agent-work accounting (cost / wall-time / success-rate / ROI) over the run
 receipts that onmc loop and swarm write. Honest: cost is n/a when a receipt
 did not report it — never fabricated.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ today    Account today's agent work: cost, wall-time, success-rate,          │
│          breakdowns.                                                         │
│ project  Account all agent work in this project across every run receipt.    │
│ roi      Show an honestly-labelled ROI *estimate* (est) over all receipts.   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc ledger project`

```text
Usage: onmc ledger project [OPTIONS]

 Account all agent work in this project across every run receipt.

 Aggregates cost, wall-time, success-rate, and per-model / per-agent
 breakdowns from every ``run-*.json`` receipt.  Honest about missing cost
 data via the summary note.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON to stdout.                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc ledger roi`

```text
Usage: onmc ledger roi [OPTIONS]

 Show an honestly-labelled ROI *estimate* (est) over all receipts.

 Compares real agent wall-clock time against a transparent assumption of
 human minutes per run.  The result is explicitly marked ``est`` and carries
 its assumption — it is an estimate, not a measurement.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON to stdout.                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc ledger today`

```text
Usage: onmc ledger today [OPTIONS]

 Account today's agent work: cost, wall-time, success-rate, breakdowns.

 Reads run receipts from ``.agent-memory/receipts/`` dated today (UTC).
 Cost is shown as ``n/a`` when no receipt reported it — never fabricated.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON to stdout.                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc llm`

```text
Usage: onmc llm [OPTIONS] COMMAND [ARGS]...

 Configure optional LLM providers.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ status     Show optional LLM provider configuration status.                  │
│ configure  Persist optional LLM provider settings to the local ONMC config.  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc llm configure`

```text
Usage: onmc llm configure [OPTIONS]

 Persist optional LLM provider settings to the local ONMC config.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --provider               [anthropic|openai|olla  LLM provider to          │
│                             ma|litellm|mock]        configure.               │
│                                                     [required]               │
│ *  --model                  TEXT                    Default model name.      │
│                                                     [required]               │
│    --api-key-env-var        TEXT                    Environment variable to  │
│                                                     read the provider API    │
│                                                     key from.                │
│    --temperature            FLOAT RANGE             Default temperature.     │
│                             [0.0<=x<=2.0]           [default: 0.0]           │
│    --max-tokens             INTEGER RANGE [x>=1]    Default maximum output   │
│                                                     tokens.                  │
│                                                     [default: 1024]          │
│    --help                                           Show this message and    │
│                                                     exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc llm status`

```text
Usage: onmc llm status [OPTIONS]

 Show optional LLM provider configuration status.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc loop`

```text
Usage: onmc loop [OPTIONS]

 Run a memory-grounded autonomous loop that avoids recorded dead-ends.

 Each iteration recalls FAILED_APPROACH memories so the agent cannot repeat
 known dead-ends.  Wins are recorded as DECISION memories; losses are
 recorded as FAILED_APPROACH memories so future iterations block them.

 A tamper-evident run receipt is written to .agent-memory/receipts/ after
 every non-dry-run invocation.  A checkpoint is saved to
 .onmc/loop-state/ after every iteration so runs can be resumed with
 --resume.


 Examples
 --------
 onmc loop --goal "fix the cache invalidation bug" --verify "pytest tests/"
 onmc loop --goal "fix the bug" --agent codex --verify "pytest tests/"
 onmc loop --goal "fix the bug" --agent opencode --verify "pytest tests/"
 onmc loop --spec goal.txt --max-iterations 5 --budget-tokens 50000
 onmc loop --goal "refactor auth module" --dry-run          # preview prompt
 only
 onmc loop --goal "fix flaky test" --json                   # machine-readable
 output
 onmc loop --goal "fix bug" --max-cost-usd 2.00             # stop at $2 spend
 onmc loop --goal "fix bug" --max-wall-seconds 300          # stop after 5
 minutes
 onmc loop --goal "fix bug" --isolate                       # run in isolated
 worktree
 onmc loop --goal "fix bug" --max-wall-seconds 60 && onmc loop --goal "fix bug"
 --resume
 onmc loop --template ci-healer                             # use built-in
 template
 onmc loop --template issue-to-pr --goal "implement #42"   # template + custom
 goal
 onmc loop --list-templates                                 # show all
 templates

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --goal                    TEXT                  Goal text for the loop       │
│                                                 (inline).                    │
│ --spec                    TEXT                  Path to a file containing    │
│                                                 the goal text.               │
│ --template                TEXT                  Use a built-in loop template │
│                                                 to prefill goal, verify, and │
│                                                 limits. Available:           │
│                                                 ci-healer, pr-babysitter,    │
│                                                 issue-to-pr. Explicit flags  │
│                                                 override template defaults.  │
│                                                 Use --list-templates to see  │
│                                                 all templates with           │
│                                                 descriptions.                │
│ --list-templates                                Print available built-in     │
│                                                 loop templates and exit.     │
│ --agent                   TEXT                  Agent CLI to use: claude     │
│                                                 (default), codex, or         │
│                                                 opencode.                    │
│                                                 [default: claude]            │
│ --max-iterations          INTEGER RANGE [x>=1]  Maximum loop iterations.     │
│ --budget-tokens           INTEGER RANGE [x>=1]  Stop when total tokens       │
│                                                 exceed this budget.          │
│ --verify                  TEXT                  Shell command run after each │
│                                                 iteration to verify success. │
│ --dry-run                                       Build the prompt and recall  │
│                                                 dead-ends without invoking   │
│                                                 the agent or verify. Safe to │
│                                                 run without any configured   │
│                                                 agent.                       │
│ --json                                          Print the full result as     │
│                                                 JSON.                        │
│ --max-cost-usd            FLOAT RANGE [x>=0.0]  Stop before the next         │
│                                                 iteration when cumulative    │
│                                                 cost (USD) exceeds this      │
│                                                 value.                       │
│ --max-wall-seconds        INTEGER RANGE [x>=1]  Stop before the next         │
│                                                 iteration when elapsed       │
│                                                 wall-clock seconds exceed    │
│                                                 this.                        │
│ --isolate                                       Run the loop inside a fresh  │
│                                                 git worktree so changes are  │
│                                                 isolated. On success         │
│                                                 (converged) the worktree     │
│                                                 path is preserved; on        │
│                                                 failure the worktree is      │
│                                                 removed and no partial       │
│                                                 changes leak into the        │
│                                                 working tree. Degrades       │
│                                                 gracefully (warns + runs     │
│                                                 in-place) when git worktree  │
│                                                 add fails.                   │
│ --resume                                        Resume a previous run from   │
│                                                 its last checkpoint. Loads   │
│                                                 the checkpoint for the       │
│                                                 matching goal + verify pair  │
│                                                 and continues from the next  │
│                                                 iteration, preserving all    │
│                                                 prior contracts and          │
│                                                 counters. No-op when no      │
│                                                 matching checkpoint exists.  │
│ --help                                          Show this message and exit.  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc loop-templates`

```text
Usage: onmc loop-templates [OPTIONS]

 List available built-in loop templates.

 Each template prefills goal, verify command, and iteration limits for
 common autonomous-agent workflows.  Pass a template name to
 ``onmc loop --template <name>`` to use it.


 Available templates
 -------------------
 ci-healer      Fix failing CI without changing public behaviour.
 pr-babysitter  Keep a pull request green (rebase, resolve conflicts).
 issue-to-pr    Implement a GitHub issue as a PR-ready change.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc mcp`

```text
Usage: onmc mcp [OPTIONS] COMMAND [ARGS]...

 MCP Trust Gateway — classify tool calls against a policy.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ check   Classify MCP tool calls from a JSONL file (or stdin) against the     │
│         trust policy.                                                        │
│ policy  Manage the MCP trust policy file (.onmc/mcp-policy.yaml).            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc mcp check`

```text
Usage: onmc mcp check [OPTIONS] [CALLS_FILE]

 Classify MCP tool calls from a JSONL file (or stdin) against the trust policy.

 Reads recorded tool-call events, applies the .onmc/mcp-policy.yaml policy,
 scans arguments for embedded secrets and prompt-injection phrases, and
 renders a decision table.

 Exit codes:

 - 0 — all calls pass the --fail-on threshold
 - 1 — at least one call blocked / requires approval (when threshold met)
 - 2 — usage error

 Example::

     onmc mcp check calls.jsonl --fail-on block
     cat calls.jsonl | onmc mcp check - --json

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   [calls_file]      PATH  Path to a JSONL file of recorded tool calls.  Each │
│                           line: {"server": "...", "tool": "...", "args":     │
│                           {...}}.  Omit or pass '-' to read from stdin.      │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                      Emit classifications as JSON to stdout.          │
│ --fail-on             TEXT  Exit non-zero when any decision has this verdict │
│                             or worse.  One of: block, approval_required.     │
│                             Default: block.                                  │
│                             [default: block]                                 │
│ --no-audit-log              Skip writing to .onmc/mcp-audit.log.             │
│ --repo                PATH  Repo root for locating .onmc/mcp-policy.yaml.    │
│ --help                      Show this message and exit.                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc mcp policy`

```text
Usage: onmc mcp policy [OPTIONS] COMMAND [ARGS]...

 Manage the MCP trust policy file (.onmc/mcp-policy.yaml).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ init  Write a documented starter .onmc/mcp-policy.yaml for the MCP trust     │
│       gateway.                                                               │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc mcp policy init`

```text
Usage: onmc mcp policy init [OPTIONS] [PATH]

 Write a documented starter .onmc/mcp-policy.yaml for the MCP trust gateway.

 The generated file declares example server allow-lists, tool scopes
 (read / write / network), and approval-required lists with inline comments.

 Re-running is safe — the file is not overwritten unless --force is passed.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   [path]      PATH  Repo root.  Defaults to current directory.               │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --force          Overwrite an existing policy file.                          │
│ --help           Show this message and exit.                                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc membudget`

```text
Usage: onmc membudget [OPTIONS] COMMAND [ARGS]...

 Memory-budget guard: report store size, flag over-budget, suggest
 consolidations.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ check  Report memory-store size and suggest consolidation actions.           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc membudget check`

```text
Usage: onmc membudget check [OPTIONS]

 Report memory-store size and suggest consolidation actions.

 Reads every memory entry and computes total UTF-8 byte size across
 title + summary + details.  Flags when the total exceeds --limit (default
 256 KiB) and emits advisory suggestions:

 \b
 - DROP_STALE    — entries with staleness=stale/orphaned
 - MERGE_DUPLICATES — near-duplicate pairs (≥55% token overlap, same kind)
 - MOVE_TO_TOPIC — entries with details > 4 KiB (store a reference instead)

 Advisory only — never deletes or mutates the store.

 Examples:

     onmc membudget check               # human-readable report

     onmc membudget check --json        # JSON envelope for pipelines

     onmc membudget check --limit 131072          # 128 KiB budget

     onmc membudget check --fail-on-over          # exit 1 when over budget

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                       Emit a JSON envelope {"kind": "membudget",      │
│                              "report": {...}} for pipeline composition.      │
│ --limit               BYTES  Budget ceiling in bytes (default: 262144 = 256  │
│                              KiB).                                           │
│                              [default: 262144]                               │
│ --fail-on-over               Exit 1 when the store is over budget (useful in │
│                              CI).                                            │
│ --help                       Show this message and exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memguard`

```text
Usage: onmc memguard [OPTIONS] COMMAND [ARGS]...

 Memory-integrity firewall: scan memory entries for adversarial content.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ scan  Scan the onmc memory store for adversarial content.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memguard scan`

```text
Usage: onmc memguard scan [OPTIONS]

 Scan the onmc memory store for adversarial content.

 Reads every memory entry and checks for:

 \b
 - Prompt-injection / system-prompt override phrases (MG-INJ-*)
 - Credential exfiltration attempts (MG-EXF-*)
 - SSH authorized_keys writes and reverse-shell one-liners (MG-SSH-*)
 - Invisible/dangerous Unicode: zero-width chars, bidi overrides,
   tag chars (MG-UNI-*)

 Pure stdlib — deterministic, offline, no network calls.

 Examples:

     onmc memguard scan               # human-readable report

     onmc memguard scan --json        # JSON envelope for pipelines

     onmc memguard scan --fail-on high  # exit 1 when high+ findings exist

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                           Emit a JSON envelope {"kind": "memguard",   │
│                                  "report": {...}} for pipeline composition.  │
│ --include-clean                  Include clean (no-finding) entries in the   │
│                                  output.                                     │
│ --fail-on              SEVERITY  Exit 1 when a finding exists at or above    │
│                                  SEVERITY (critical/high/medium/low).        │
│ --help                           Show this message and exit.                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memory`

```text
Usage: onmc memory [OPTIONS] COMMAND [ARGS]...

 Inspect stored memory.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ list     List stored memory entries.                                         │
│ add      Add a task-derived memory artifact.                                 │
│ show     Show a single memory entry with provenance.                         │
│ confirm  Mark a memory record as verified useful.                            │
│ reject   Mark a memory record as wrong or stale.                             │
│ edit     Edit a memory summary and reset its feedback score.                 │
│ verify   Re-check anchored memories against the filesystem and record        │
│          staleness.                                                          │
│ prune    Remove orphaned generated memories (manual memories are always      │
│          preserved).                                                         │
│ embed    Pre-build semantic embedding vectors for all memories.              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memory add`

```text
Usage: onmc memory add [OPTIONS] TASK_ID

 Add a task-derived memory artifact.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    task_id      TEXT  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --type                  [fix|did_not_work|desig  Task-derived memory      │
│                            n_conflict|gotcha|invar  artifact type.           │
│                            iant|validation]         [required]               │
│ *  --title                 TEXT                     Short artifact title.    │
│                                                     [required]               │
│ *  --summary               TEXT                     What worked, failed, or  │
│                                                     conflicted.              │
│                                                     [required]               │
│    --why-it-matters        TEXT                     Why a future agent or    │
│                                                     engineer should keep     │
│                                                     this in mind.            │
│                                                     [default: Preserve this  │
│                                                     task outcome so future   │
│                                                     work starts from a known │
│                                                     result.]                 │
│    --apply-when            TEXT                     When this guidance       │
│                                                     should be used.          │
│    --avoid-when            TEXT                     When this guidance       │
│                                                     should not be applied.   │
│    --evidence              TEXT                     Evidence from the task   │
│                                                     or attempts.             │
│                                                     [default: Recorded from  │
│                                                     task-scoped work.]       │
│    --file                  TEXT                     Repeat to record related │
│                                                     file paths.              │
│    --module                TEXT                     Repeat to record related │
│                                                     module names.            │
│    --confidence            FLOAT RANGE              Confidence from 0.0 to   │
│                            [0.0<=x<=1.0]            1.0.                     │
│                                                     [default: 0.7]           │
│    --help                                           Show this message and    │
│                                                     exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memory confirm`

```text
Usage: onmc memory confirm [OPTIONS] MEMORY_ID

 Mark a memory record as verified useful.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    memory_id      TEXT  [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memory edit`

```text
Usage: onmc memory edit [OPTIONS] MEMORY_ID

 Edit a memory summary and reset its feedback score.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    memory_id      TEXT  [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memory embed`

```text
Usage: onmc memory embed [OPTIONS]

 Pre-build semantic embedding vectors for all memories.

 Vectors are cached in the local SQLite database (migration v6).  Subsequent
 searches use the cache, so this command is optional — vectors are also built
 lazily on first search when embeddings are enabled.  Run it to warm the
 cache or after switching to a different real-model embedder.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --force          Recompute vectors even when a valid cache entry exists.     │
│ --help           Show this message and exit.                                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memory list`

```text
Usage: onmc memory list [OPTIONS]

 List stored memory entries.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --kind                           [doc_fact|decision|i  Filter by memory      │
│                                  nvariant|hotspot|git  kind.                 │
│                                  _pattern|validation_                        │
│                                  rule|failed_approach                        │
│                                  |design_conflict|got                        │
│                                  cha]                                        │
│ --source                         [git|doc|code|manual  Filter by memory      │
│                                  |manual_seed|llm_ext  source type.          │
│                                  racted|transcript|gi                        │
│                                  thub_pr|session]                            │
│ --type                           [fix|did_not_work|de  Filter task-derived   │
│                                  sign_conflict|gotcha  memory artifacts by   │
│                                  |invariant|validatio  type.                 │
│                                  n]                                          │
│ --min-confidence                 FLOAT RANGE           Filter by minimum     │
│                                  [0.0<=x<=1.0]         confidence.           │
│ --confirmed                                            Show only explicitly  │
│                                                        confirmed memories.   │
│ --wide              --compact                          Show a wider, more    │
│                                                        readable memory       │
│                                                        table.                │
│                                                        [default: wide]       │
│ --help                                                 Show this message and │
│                                                        exit.                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memory prune`

```text
Usage: onmc memory prune [OPTIONS]

 Remove orphaned generated memories (manual memories are always preserved).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --orphaned          Remove memories whose anchor file no longer exists.      │
│ --dry-run           Show what would be deleted without deleting.             │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memory reject`

```text
Usage: onmc memory reject [OPTIONS] MEMORY_ID

 Mark a memory record as wrong or stale.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    memory_id      TEXT  [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memory show`

```text
Usage: onmc memory show [OPTIONS] MEMORY_ID

 Show a single memory entry with provenance.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    memory_id      TEXT  [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memory verify`

```text
Usage: onmc memory verify [OPTIONS]

 Re-check anchored memories against the filesystem and record staleness.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memory-diff`

```text
Usage: onmc memory-diff [OPTIONS] COMMIT_A COMMIT_B

 Show what repo knowledge changed between two commits.

 Diffs the committed `.agent-memory/` JSON snapshots at commitA and commitB.
 Reports added, removed, and changed memory entries by id and title.

 When `.agent-memory/` is not committed at either point, falls back to a plain
 git diff of changed files and clearly labels the output as fallback mode.

 Run `onmc sync --commit` and commit `.agent-memory/` to unlock full diffs.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    commit_a      TEXT  Older commit-ish (hash, tag, or branch name).       │
│                          [required]                                          │
│ *    commit_b      TEXT  Newer commit-ish (hash, tag, or branch name).       │
│                          [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memprovider`

```text
Usage: onmc memprovider [OPTIONS] COMMAND [ARGS]...

 Manage and query external memory providers that augment onmc's built-in store
 (mem0, supermemory, builtin). Providers run alongside the built-in store —
 they never replace it.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ list    List all registered memory providers and their availability.         │
│ search  Search across available memory providers and print attributed hits.  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memprovider list`

```text
Usage: onmc memprovider list [OPTIONS]

 List all registered memory providers and their availability.

 The ``builtin`` provider (backed by onmc's own SQLite store) is always
 listed first and is always available.  Optional providers (mem0,
 supermemory) report ``available: false`` when their dependency or API key
 is absent.

 Examples:

     onmc memprovider list

     onmc memprovider list --json

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit a JSON envelope instead of human-readable text.         │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memprovider search`

```text
Usage: onmc memprovider search [OPTIONS] QUERY

 Search across available memory providers and print attributed hits.

 Results from each available provider are merged and attributed via the
 ``provider`` field.  Use ``--provider`` to restrict to a single backend.

 Providers that are unavailable (missing dependency or API key) are silently
 skipped unless named explicitly via ``--provider``.

 Examples:

     onmc memprovider search "cache invalidation"

     onmc memprovider search "auth bug" --provider builtin --json

     onmc memprovider search "ETF allocation" --provider mem0 --limit 5

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    query      TEXT  Free-text search query. [required]                     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --provider  -p      NAME                       Restrict search to this       │
│                                                provider name (e.g.           │
│                                                'builtin', 'mem0').           │
│ --limit     -n      INTEGER RANGE [1<=x<=100]  Maximum hits per provider.    │
│                                                [default: 10]                 │
│ --json                                         Emit a JSON envelope instead  │
│                                                of human-readable text.       │
│ --help                                         Show this message and exit.   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memstage`

```text
Usage: onmc memstage [OPTIONS] COMMAND [ARGS]...

 Write-approval staging queue: propose memory writes, review diffs, then
 approve or reject — nothing lands in the store without your sign-off.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ add      Stage a proposed memory write into the pending queue.               │
│ list     List pending proposals with ids and one-line gists.                 │
│ diff     Show the full proposed entry in unified-diff style.                 │
│ approve  Approve a pending proposal and persist it to the memory store.      │
│ reject   Reject a pending proposal: drop it and keep an audit trail.         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memstage add`

```text
Usage: onmc memstage add [OPTIONS] TEXT

 Stage a proposed memory write into the pending queue.

 The entry is NOT written to the memory store — it waits in the queue
 until you run ``approve`` or ``reject``. Review the diff first with
 ``onmc memstage diff <id>``.

 Examples:

     onmc memstage add "Always run tests before pushing"

     onmc memstage add "Stripe webhook secret rotates on redeploy" \
       --kind gotcha --title "Stripe webhook secret rotates" \
       --reason "Burnt 2h on this"

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    text      TEXT  The proposed memory entry body (the summary).           │
│                      [required]                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --title         TEXT  Short title for the memory entry.                      │
│ --kind          TEXT  Memory kind (doc_fact, decision, invariant, hotspot,   │
│                       git_pattern, validation_rule, failed_approach,         │
│                       design_conflict, gotcha). Defaults to 'doc_fact'.      │
│ --reason        TEXT  Why this write is being proposed.                      │
│ --json                Emit the staged proposal as JSON.                      │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memstage approve`

```text
Usage: onmc memstage approve [OPTIONS] PROPOSAL_ID

 Approve a pending proposal and persist it to the memory store.

 The approved entry is written via the real memory record path
 (``add_manual_memory``) so it lands in the SQLite store with full
 provenance. The proposal is then removed from the pending queue and an
 audit record is written under ``.onmc/memstage/audit/``.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    proposal_id      TEXT  Proposal id to approve (from 'onmc memstage      │
│                             list').                                          │
│                             [required]                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the audit record as JSON.                               │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memstage diff`

```text
Usage: onmc memstage diff [OPTIONS] PROPOSAL_ID

 Show the full proposed entry in unified-diff style.

 Compares an empty baseline (entry doesn't exist yet) against the
 proposed content so every added line is visible. A ``+`` line is
 something that *would* land in the store on approve.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    proposal_id      TEXT  Proposal id to diff (from 'onmc memstage list'). │
│                             [required]                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memstage list`

```text
Usage: onmc memstage list [OPTIONS]

 List pending proposals with ids and one-line gists.

 Shows proposals in queue order (by seq). Each line contains the
 proposal id and title for quick scanning. Use ``diff <id>`` to see
 the full proposed entry.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit pending proposals as JSON.                              │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc memstage reject`

```text
Usage: onmc memstage reject [OPTIONS] PROPOSAL_ID

 Reject a pending proposal: drop it and keep an audit trail.

 The proposal is removed from the pending queue. An audit record is
 written under ``.onmc/memstage/audit/`` so the decision is traceable.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    proposal_id      TEXT  Proposal id to reject (from 'onmc memstage       │
│                             list').                                          │
│                             [required]                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --reason        TEXT  Why this proposal is being rejected.                   │
│ --json                Emit the audit record as JSON.                         │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc mine`

```text
Usage: onmc mine [OPTIONS]

 Mine Claude Code session transcripts into ONMC memory.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --github               Mine GitHub PRs and reviews from the repo remote.     │
│ --session        TEXT  Mine a specific session id.                           │
│ --dry-run              Show findings without writing them.                   │
│ --since          TEXT  Only process transcripts newer than this value.       │
│ --no-llm               Skip LLM extraction and only inspect transcript       │
│                        availability.                                         │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc mission`

```text
Usage: onmc mission [OPTIONS] GOAL

 Run the engineering pipeline end-to-end into one mission plan.

 Composes recorded dead-ends (guard) + a deterministic context pack +
 the code-graph blast radius + the swarm units the mission would run.
 Plan mode (the default) is offline and deterministic and spawns no
 agents; ``--execute`` additionally allocates the swarm manifest.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    goal      TEXT  The mission goal — what you want done. [required]       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --execute                                    Hand the plan to the swarm      │
│                                              (materialise its manifest).     │
│                                              Default is plan mode: a safe,   │
│                                              offline dry-run that spawns     │
│                                              nothing.                        │
│ --concurrency        INTEGER RANGE [x>=1]    Advisory swarm fan-out width.   │
│                                              [default: 4]                    │
│ --budget             INTEGER RANGE [x>=400]  Context-pack markdown character │
│                                              budget.                         │
│                                              [default: 12000]                │
│ --json                                       Emit the mission plan as JSON   │
│                                              instead of markdown.            │
│ --help                                       Show this message and exit.     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc missioncontrol`

```text
Usage: onmc missioncontrol [OPTIONS] [SWARM_ID]

 Live, read-only dashboard for an onmc swarm.

 Reads the swarm manifest + tamper-evident receipts and shows each unit's
 state (pending/queued/running/done/failed/aborted), whether a receipt
 exists, its verified flag and diff_sha, plus the abort-sentinel state.
 Never mutates swarm state.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   [swarm_id]      TEXT  Swarm id to inspect. Omit with --all to list swarms. │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --all           List all swarms under .onmc/swarm and exit.                  │
│ --json          Emit machine-readable JSON instead of a table.               │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc nightshift`

```text
Usage: onmc nightshift [OPTIONS]

 Plan a bounded, verified overnight swarm + preview the morning digest.

 Collects the backlog from repeated ``--goal`` and/or a ``--file``,
 de-duplicates and orders it deterministically, and truncates to
 ``--budget`` units. Dry-run (the default) is offline and spawns no
 agents: it prints the plan and a sample morning digest. Only ``--json``
 suppresses the digest, emitting the plan as JSON.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --goal                       TEXT     A backlog goal for the overnight       │
│                                       swarm. Repeatable.                     │
│ --file                       PATH     Read backlog goals from a file (one    │
│                                       per line, # comments ignored).         │
│ --budget                     INTEGER  Max swarm units to schedule overnight. │
│                                       [default: 5]                           │
│ --dry-run    --no-dry-run             Plan only — spawn nothing (default).   │
│                                       Print the plan + a sample morning      │
│                                       digest.                                │
│                                       [default: dry-run]                     │
│ --json                                Emit the nightshift plan as JSON.      │
│ --help                                Show this message and exit.            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc nomistakes`

```text
Usage: onmc nomistakes [OPTIONS] GOAL

 Run the No-Mistakes PR gate: audit + eval + autopilot + receipt verdict.

 Approval requires deterministic preflight gates to pass and a verified
 receipt from the underlying autopilot run.  L0/L1 are no-write modes. L2+
 can act, verify, learn, and emit a receipt.


 Examples
 --------
 onmc nomistakes "fix failing CI" --verify "pytest -q"
 onmc nomistakes "review this PR" --agent codex --eval-fail-under 80
 onmc nomistakes "stabilize flaky tests"       --plan-with claude-opus-4-5
 --execute-with claude-haiku-4-5
 onmc nomistakes "inspect risk only" --autonomy L1 --dry-run

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    goal      TEXT  Goal for the PR/CI gate. [required]                     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --agent                               TEXT               Agent CLI to use:   │
│                                                          claude (default),   │
│                                                          codex, or opencode. │
│                                                          [default: claude]   │
│ --autonomy                            TEXT               Autonomy level: L0  │
│                                                          observe, L1 advise, │
│                                                          L2 act+prove, L3    │
│                                                          extended, L4        │
│                                                          reserved.           │
│                                                          [default: L2]       │
│ --verify                              TEXT               Shell verifier      │
│                                                          required for        │
│                                                          approval.           │
│                                                          [default: pytest]   │
│ --max-iterations                      INTEGER RANGE      Maximum loop        │
│                                       [x>=1]             iterations.         │
│                                                          [default: 6]        │
│ --budget-tokens                       INTEGER RANGE      Stop when total     │
│                                       [x>=1]             tokens exceed this  │
│                                                          budget.             │
│                                                          [default: 80000]    │
│ --max-cost-usd                        FLOAT RANGE        USD cost ceiling    │
│                                       [x>=0.0]           for the run.        │
│                                                          [default: 3.0]      │
│ --max-wall-seconds                    INTEGER RANGE      Wall-clock ceiling  │
│                                       [x>=1]             in seconds.         │
│                                                          [default: 900]      │
│ --audit-fail-on                       TEXT               Block on audit      │
│                                                          findings at or      │
│                                                          above: critical,    │
│                                                          high, medium, low,  │
│                                                          info.               │
│                                                          [default: high]     │
│ --eval-fail-under                     FLOAT RANGE        Run eval gate and   │
│                                       [0.0<=x<=100.0]    block when score is │
│                                                          below this          │
│                                                          threshold.          │
│ --plan-with                           TEXT               Model for optional  │
│                                                          PLAN step.          │
│ --execute-with                        TEXT               Model for ACT step. │
│ --isolate             --no-isolate                       Run in an isolated  │
│                                                          git worktree by     │
│                                                          default.            │
│                                                          [default: isolate]  │
│ --dry-run                                                Run gates and KNOW  │
│                                                          context without     │
│                                                          invoking the agent. │
│ --json                                                   Print               │
│                                                          machine-readable    │
│                                                          gate result.        │
│ --help                                                   Show this message   │
│                                                          and exit.           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc notify`

```text
Usage: onmc notify [OPTIONS] COMMAND [ARGS]...

 Inspect and test the context firewall notification sink.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ status  Show the active context firewall sink configuration.                 │
│ test    Emit a test event to the active sink and report where it went.       │
│ tail    Show recent events from the context firewall log (.onmc/notify.log). │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc notify status`

```text
Usage: onmc notify status [OPTIONS]

 Show the active context firewall sink configuration.

 Reads from config.yaml and env vars (env wins).  Displays the active sink
 type, log path, and masked webhook URLs when configured.

 Environment overrides:
 - ONMC_NOTIFY_ENABLED=0  disable the firewall entirely.
 - ONMC_NOTIFY_SINK       "file" | "discord" | "slack" | "none".
 - ONMC_DISCORD_WEBHOOK   Discord incoming webhook URL.
 - ONMC_SLACK_WEBHOOK     Slack incoming webhook URL.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the status as JSON instead of a rich panel.             │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc notify tail`

```text
Usage: onmc notify tail [OPTIONS]

 Show recent events from the context firewall log (.onmc/notify.log).

 Only the FileSink (the default) produces a readable local log.  Discord and
 Slack sinks route events to the webhook without storing them locally, but
 the FileSink always writes a local JSONL copy when enabled.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --lines  -n      INTEGER RANGE [x>=1]  Number of recent events to show.      │
│                                        [default: 20]                         │
│ --json                                 Emit events as a JSON array.          │
│ --help                                 Show this message and exit.           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc notify test`

```text
Usage: onmc notify test [OPTIONS]

 Emit a test event to the active sink and report where it went.

 Useful for verifying that the context firewall is correctly routed before
 connecting real hooks.  The test event has kind=generic and severity=routine.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --message  -m      TEXT  Custom message for the test event.                  │
│                          [default: test notification from onmc]              │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc onboard`

```text
Usage: onmc onboard [OPTIONS]

 Give a new dev (or agent) the guided five-minute repo tour from memory.

 Compiles an ordered sequence of stops — danger zones, load-bearing decisions,
 top playbooks, and where to look first — entirely offline from stored ONMC
 memory. Interactive by default (paginated, press Enter to advance); use
 --steps for a single non-interactive dump.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --steps          Print all tour stops at once and exit (non-interactive).    │
│                  Suitable for piping, CI, and tests.                         │
│ --help           Show this message and exit.                                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc orggraph`

```text
Usage: onmc orggraph [OPTIONS] COMMAND [ARGS]...

 Institutional-memory knowledge graph — entities, typed edges, lineage.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ build  Build the knowledge graph from stored memories and summarise it.      │
│ query  Show an entity's neighbours and the provenance (memory ids) behind    │
│        it.                                                                   │
│ why    Explain a decision: the ordered chain of edges/memories behind it.    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc orggraph build`

```text
Usage: onmc orggraph build [OPTIONS]

 Build the knowledge graph from stored memories and summarise it.

 Deterministic and offline: same brain → same graph. Prints entity/edge
 counts, a per-relation breakdown, and the most-connected entities.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the graph summary as JSON.                              │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc orggraph query`

```text
Usage: onmc orggraph query [OPTIONS] ENTITY

 Show an entity's neighbours and the provenance (memory ids) behind it.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    entity      TEXT  Entity name to inspect. [required]                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the query result as JSON.                               │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc orggraph why`

```text
Usage: onmc orggraph why [OPTIONS] DECISION

 Explain a decision: the ordered chain of edges/memories behind it.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    decision      TEXT  Decision entity name. [required]                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the lineage as JSON.                                    │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc pack`

```text
Usage: onmc pack [OPTIONS] GOAL

 Build a per-task context pack: dead-ends, decisions, reuse, files.

 Composes recorded dead-ends + decisions with a tiny code-graph slice and
 reuse hints into a terse, deterministic, offline markdown brief for a
 spawned agent.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    goal      TEXT  Goal or task description for the spawned agent.         │
│                      [required]                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --budget        INTEGER RANGE [x>=400]  Maximum markdown characters.         │
│                                         [default: 12000]                     │
│ --json                                  Emit the pack as JSON instead of     │
│                                         markdown.                            │
│ --help                                  Show this message and exit.          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc playbook`

```text
Usage: onmc playbook [OPTIONS] COMMAND [ARGS]...

 Synthesize and manage memory-derived playbooks.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ generate  Synthesize playbooks from stored memory, persist, and write        │
│           artifacts.                                                         │
│ list      List all persisted playbooks.                                      │
│ show      Show a single playbook with steps and provenance.                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc playbook generate`

```text
Usage: onmc playbook generate [OPTIONS]

 Synthesize playbooks from stored memory, persist, and write artifacts.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --no-llm          Skip the optional LLM polish pass; deterministic only.     │
│ --help            Show this message and exit.                                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc playbook list`

```text
Usage: onmc playbook list [OPTIONS]

 List all persisted playbooks.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc playbook show`

```text
Usage: onmc playbook show [OPTIONS] PLAYBOOK_ID

 Show a single playbook with steps and provenance.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    playbook_id      TEXT  Playbook ID (or prefix) to show. [required]      │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc plug`

```text
Usage: onmc plug [OPTIONS] TARGET

 Wire onmc into a target coding agent (one-shot idempotent wizard).


 Targets
 -------
 claude-code   Install Claude Code hooks + .mcp.json (safe to re-run).
 codex         Write/refresh an AGENTS.md stanza so Codex runs onmc brief
               and onmc guard at session start.
 opencode      Write/refresh an AGENTS.md stanza for OpenCode + export
               onmc skills to .opencode/skills/.
 cursor        Write/refresh .cursor/rules/onmc.md (Cursor >=0.40 format).
 omc           Write docs/integrations/omc.md with a copy-paste OMC adapter.
 omx           Write docs/integrations/omx.md with a copy-paste OMX adapter.
 all           Apply claude-code + codex + opencode + cursor (safe subset).

 All writes are idempotent — running twice never duplicates stanzas.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    target      TEXT  Agent to wire onmc into. Choices: claude-code, codex, │
│                        opencode, cursor, omc, omx, all.                      │
│                        [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc preflight`

```text
Usage: onmc preflight [OPTIONS]

 Run the exact CI quality gate locally, in the same order CI runs it.

 Mirrors ``.github/workflows/ci.yml`` step-for-step:

 1. ``ruff check .``
 2. ``mypy --strict src/oh_no_my_claudecode``
 3. ``generate-cli-reference.py --check``
 4. ``pytest tests/``

 Use ``--only`` to run a subset, e.g. ``onmc preflight --only ruff --only
 mypy``.

 Exit codes:

 - 0 — every step that ran passed (matches the CI gate)
 - 1 — one or more steps failed, or no valid step was selected
 - 2 — usage error

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --only             TEXT  Run only these steps (repeatable).  One or more of: │
│                          ruff, mypy, cliref, pytest.  Default: run all, in   │
│                          CI order.                                           │
│ --json                   Emit the PreflightReport as JSON to stdout.         │
│ --provision              Run each tool via `uv run --with <tool>` so a fresh │
│                          worktree (no dev deps installed) resolves           │
│                          ruff/mypy/pytest on demand, and pin typer<1.0 for   │
│                          the cli-reference step to match CI.                 │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc profile`

```text
Usage: onmc profile [OPTIONS] COMMAND [ARGS]...

 Show and rebuild the derived user behavioral profile (~/.onmc/user.db).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ show     Show the derived behavioral profile compiled from ~/.onmc/user.db.  │
│ rebuild  Recompute the behavioral profile from ~/.onmc/user.db and display   │
│          it.                                                                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc profile rebuild`

```text
Usage: onmc profile rebuild [OPTIONS]

 Recompute the behavioral profile from ~/.onmc/user.db and display it.

 Equivalent to `onmc profile show` — the profile is always freshly derived
 from the current user store (no cache).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Output the rebuilt profile as JSON.                          │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc profile show`

```text
Usage: onmc profile show [OPTIONS]

 Show the derived behavioral profile compiled from ~/.onmc/user.db.

 Buckets user memories into preferences, patterns, mistakes-to-avoid, and
 tooling — entirely offline, no LLM calls.  Use `onmc user add` to seed
 the profile with more memories.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Output the profile as JSON.                                  │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc proptest`

```text
Usage: onmc proptest [OPTIONS] COMMAND [ARGS]...

 Generate property/invariant tests for pure functions.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ init  Generate a fixed-seed property test from an invariant SPEC.            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc proptest init`

```text
Usage: onmc proptest init [OPTIONS] SPEC

 Generate a fixed-seed property test from an invariant SPEC.

 The spec is a JSON file describing a pure function (``import_path``) and
 the invariants it must satisfy (``range`` / ``no_substring`` /
 ``monotonic``). The generated test samples inputs with a fixed seed so
 runs are deterministic and reproducible.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    spec      PATH  Path to the invariant spec JSON file. [required]        │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --out          PATH  Directory to write the generated test into.             │
│                      [default: tests]                                        │
│ --force              Overwrite an existing test file.                        │
│ --json               Emit a JSON result instead of human text.               │
│ --help               Show this message and exit.                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc proxy`

```text
Usage: onmc proxy [OPTIONS] COMMAND [ARGS]...

 OpenAI-compatible local proxy for onmc's configured LLM provider.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ serve  Start an OpenAI-compatible proxy backed by onmc's configured LLM      │
│        provider.                                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc proxy serve`

```text
Usage: onmc proxy serve [OPTIONS]

 Start an OpenAI-compatible proxy backed by onmc's configured LLM provider.

 The server exposes two endpoints:

 \b
 POST /v1/chat/completions   ← OpenAI ChatCompletions (non-streaming)
 GET  /v1/models             ← Returns the configured model as a list entry

 External tools (Codex, Aider, Cline, Continue, …) can be pointed at
 ``http://<host>:<port>/v1`` and will use whatever LLM backend onmc is
 configured with, without needing their own API keys for that backend.

 Examples:

     onmc proxy serve

     onmc proxy serve --port 9000

     onmc proxy serve --host 0.0.0.0 --port 8760

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --port        INTEGER  TCP port to listen on. [default: 8760]                │
│ --host        TEXT     Bind address (use 0.0.0.0 to expose to the network).  │
│                        [default: 127.0.0.1]                                  │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc pull`

```text
Usage: onmc pull [OPTIONS] [SOURCE]

 Import another repo's .agent-memory/ export into this brain (federated
 memories).

 SOURCE can be a local filesystem path or a remote git URL:


   onmc pull ../sibling-repo
   onmc pull https://github.com/org/repo
   onmc pull git@github.com:org/repo.git --ref main
   onmc pull https://github.com/org/repo --label my-label
   onmc pull --all
   onmc pull --all --dry-run

 Federated memories are tagged ``federated:<repo-label>`` so they are clearly
 attributed to their source and are never confused with local memories.
 Re-pulling is idempotent: memories already present are skipped.

 When SOURCE is a git URL the repo is shallow-cloned to a temporary directory,
 its .agent-memory/ export is imported, and the clone is cleaned up
 immediately.

 Use --all to pull from every source configured in ``federation.sources`` in
 config.yaml.  One failing source never aborts the rest.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   [source]      TEXT  Local path to another repo (or its .agent-memory/      │
│                       dir), or a remote git URL (https://, git@, ssh://).    │
│                       Omit when using --all.                                 │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --all                  Pull from every source listed in federation.sources   │
│                        in config.yaml. Mutually exclusive with the SOURCE    │
│                        argument.                                             │
│ --label          TEXT  Override the short repo label used for the            │
│                        federated:<label> tag. For local paths defaults to    │
│                        the source directory name; for git URLs defaults to   │
│                        the last path segment of the URL. Ignored when --all  │
│                        is used.                                              │
│ --ref            TEXT  Branch, tag, or commit-ish to check out when cloning  │
│                        a remote git URL. Ignored for local paths and when    │
│                        --all is used.                                        │
│ --dry-run              List what would be pulled without writing any         │
│                        memories (--all only).                                │
│ --json                 Emit a machine-readable JSON summary to stdout.       │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc quest`

```text
Usage: onmc quest [OPTIONS] COMMAND [ARGS]...

 Gamified RPG backlog: XP from verified runs, levels, bosses, loot.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ log           Show the full quest log: level, XP, active quests, boss        │
│               fights, loot.                                                  │
│ achievements  List all unlocked achievements.                                │
│ stats         Show level, total XP, streak, and run counts.                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc quest achievements`

```text
Usage: onmc quest achievements [OPTIONS]

 List all unlocked achievements.

 Achievements are milestone markers based on verified-run counts,
 streak length, boss defeats, and level reached.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit achievements as JSON.                                   │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc quest log`

```text
Usage: onmc quest log [OPTIONS]

 Show the full quest log: level, XP, active quests, boss fights, loot.

 XP is earned from verified ``onmc loop`` / ``onmc swarm`` runs.
 Boss fights are high-risk open tasks. Recent loot is the last 10
 verified completions.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the quest log as JSON.                                  │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc quest stats`

```text
Usage: onmc quest stats [OPTIONS]

 Show level, total XP, streak, and run counts.

 A compact summary suitable for dashboards or status lines.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit stats as JSON.                                          │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc recall`

```text
Usage: onmc recall [OPTIONS] [QUERY]

 Search memory for past incidents matching an error or stacktrace.

 Paste an error message or stacktrace as an argument or pipe it via stdin.
 Returns prior failures/fixes that match, ranked by relevance.

 Examples:

   onmc recall "TypeError: cannot read property x of undefined"

   cat error.log | onmc recall

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   [query]      TEXT  Error text or stacktrace to search for. Omit to read    │
│                      from stdin (pipe-friendly: `cmd 2>&1 | onmc recall`).   │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --limit        INTEGER RANGE [x>=1]  Maximum number of incident matches to   │
│                                      return.                                 │
│                                      [default: 8]                            │
│ --terse                              Emit compact terse output (overrides    │
│                                      ONMC_TERSE env var).                    │
│ --help                               Show this message and exit.             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc registry`

```text
Usage: onmc registry [OPTIONS] COMMAND [ARGS]...

 Agent reputation trust ledger — aggregate signed attestations into a
 queryable, rankable track record.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ add    Verify + ingest one attestation into the persisted trust ledger.      │
│ rank   Show the trust leaderboard — agents ranked by trust score.            │
│ agent  Show one agent's full reputation + its attestation history count.     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc registry add`

```text
Usage: onmc registry add [OPTIONS] ATTESTATION_FILE

 Verify + ingest one attestation into the persisted trust ledger.

 Reads the attestation, verifies its signature (an unverifiable one is
 recorded and flagged, never counted toward trust), appends it to the
 ledger at ``.onmc/registry.json``, recomputes reputations, and prints
 the affected agent's updated line. Exits non-zero when the file cannot be
 read at all.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    attestation_file      TEXT  Path to an attestation JSON produced by     │
│                                  `attest sign --json`.                       │
│                                  [required]                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --secret        TEXT  Shared secret for HMAC verification (else              │
│                       ONMC_ATTEST_SECRET).                                   │
│ --json                Emit the updated agent line as JSON.                   │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc registry agent`

```text
Usage: onmc registry agent [OPTIONS] SUBJECT

 Show one agent's full reputation + its attestation history count.

 Exits non-zero when the subject has no attestations in the ledger.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    subject      TEXT  The agent subject (identity) to look up. [required]  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --secret        TEXT  Shared secret for HMAC verification (else              │
│                       ONMC_ATTEST_SECRET).                                   │
│ --json                Emit the agent's reputation as JSON.                   │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc registry rank`

```text
Usage: onmc registry rank [OPTIONS]

 Show the trust leaderboard — agents ranked by trust score.

 Recomputes every agent's reputation from the persisted ledger and ranks
 them by ``trust_score`` (descending, stable tiebreak by subject). An
 empty ledger prints a friendly note.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --secret        TEXT  Shared secret for HMAC verification (else              │
│                       ONMC_ATTEST_SECRET).                                   │
│ --json                Emit the ranked leaderboard as JSON.                   │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc registry-demo`

```text
Usage: onmc registry-demo [OPTIONS]

 Proof-of-concept command registered with zero edits to ``cli.py``.

 Demonstrates that a self-contained feature package can add a CLI command
 purely via the auto-discovery hook.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the confirmation as JSON.                               │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc release`

```text
Usage: onmc release [OPTIONS]

 Draft the next release from conventional-commit history.

 Classifies commit subjects since the last tag into a semver bump (feat ->
 minor, fix -> patch, "!"/BREAKING -> major, otherwise patch), computes the
 next version, and renders a CHANGELOG entry in the repo's format.
 Deterministic and offline. When the external git-cliff binary is installed
 it renders the CHANGELOG entry (best-in-class); otherwise the built-in
 renderer is used — pass --no-git-cliff to force the built-in one. Dry-run by
 default — pass --write to bump pyproject.toml and prepend the entry to
 CHANGELOG.md. Never tags or pushes.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --write        --dry-run           Edit pyproject.toml + CHANGELOG.md        │
│                                    (default: dry-run).                       │
│                                    [default: dry-run]                        │
│ --json                             Emit the drafted release as JSON.         │
│ --git-cliff    --no-git-cliff      Use git-cliff to render the CHANGELOG     │
│                                    when its binary is on PATH (default: on;  │
│                                    falls back to the built-in renderer when  │
│                                    absent).                                  │
│                                    [default: git-cliff]                      │
│ --help                             Show this message and exit.               │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc replay`

```text
Usage: onmc replay [OPTIONS] COMMAND [ARGS]...

 Replay Lab — re-run a recorded session and produce a regression report.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ run  Re-derive onmc memory hits over a recorded trace session.               │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc replay run`

```text
Usage: onmc replay run [OPTIONS] SESSION_ID_OR_PATH

 Re-derive onmc memory hits over a recorded trace session.

 Loads a session from .onmc/traces/<session-id>.jsonl (or a direct JSONL path),
 then for each query-bearing event re-runs compile_recall and compile_guard
 against the current brain.  Produces a regression report showing which steps
 memory would have influenced.

 No LLM is called.  Deterministic and offline.

 Examples:

   onmc replay run tr_abc123def456

   onmc replay run tr_abc123def456 --compare

   onmc replay run /path/to/session.jsonl --json

   onmc replay run tr_abc123def456 --without-memory

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    session_id_or_path      TEXT  Session ID (tr_…) to load from            │
│                                    .onmc/traces/, or a direct path to a      │
│                                    .jsonl session file.                      │
│                                    [required]                                │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --compare                 Run both with-memory and without-memory conditions │
│                           and show a side-by-side delta table.               │
│ --without-memory          Run the cold (no-memory) baseline only. Ignored    │
│                           when --compare is used.                            │
│ --json                    Emit machine-readable JSON to stdout.              │
│ --help                    Show this message and exit.                        │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc report`

```text
Usage: onmc report [OPTIONS]

 Generate a shareable agent-readiness report.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --output  -o      PATH  Write the markdown report to this path.              │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc reuse`

```text
Usage: onmc reuse [OPTIONS] QUERY

 Surface existing code that already does a thing — reuse before reimplementing.

 Indexes the repo with stdlib `ast` and ranks top-level functions/classes by
 how well their name, docstring, and argument names match your query.
 Entirely offline and deterministic — no LLM, no network.

 With ``--ast-grep`` (and the ``ast-grep``/``sg`` binary installed), also runs
 structural AST-pattern matching that catches structurally-similar code even
 when variable names differ.

 Examples:

   onmc reuse "tokenize text into words"

   onmc reuse tokenize --json

   onmc reuse "def $F($$$ARGS):" --ast-grep

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    query      TEXT  A description of the behaviour you need, or an         │
│                       existing symbol name.                                  │
│                       [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --limit                        INTEGER RANGE [x>=1]  Maximum number of reuse │
│                                                      hits to return.         │
│                                                      [default: 8]            │
│ --json                                               Emit the ranked hits as │
│                                                      JSON instead of a       │
│                                                      table.                  │
│ --ast-grep    --no-ast-grep                          Use ast-grep (the       │
│                                                      'ast-grep' or 'sg'      │
│                                                      binary) for             │
│                                                      structural/AST-pattern  │
│                                                      matching in addition to │
│                                                      the text heuristic.     │
│                                                      No-op when neither      │
│                                                      binary is on PATH       │
│                                                      (falls back to          │
│                                                      text-only, zero         │
│                                                      regression).            │
│                                                      [default: no-ast-grep]  │
│ --help                                               Show this message and   │
│                                                      exit.                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc review`

```text
Usage: onmc review [OPTIONS]

 Compile repo-aware review context and critique the proposed approach.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --task              TEXT  Task or proposed change to review. [required]   │
│    --input-file        PATH  Optional file containing plan, diff, or notes.  │
│    --no-llm                  Use heuristic fallback instead of the           │
│                              configured LLM.                                 │
│    --help                    Show this message and exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc roast`

```text
Usage: onmc roast [OPTIONS]

 Roast this repo's agent-readiness — a blunt 0-100 score + findings.

 Deterministic and offline: composes hotspot memory coverage, the
 agent-config audit grade, brain size, and conventions presence into a
 single shareable score. Same repo always yields the same roast.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the roast report as JSON.                               │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc route`

```text
Usage: onmc route [OPTIONS] TASK

 Deterministically route a task to an agent/model/strategy/gate.

 Pure keyword/intent matching — no LLM call. The same task always yields
 the same decision.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    task      TEXT  The task description to route. [required]               │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the decision as JSON.                                   │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc savings`

```text
Usage: onmc savings [OPTIONS]

 Show a shareable 'Memory Wrapped' token-ROI card.

 Renders a screenshot-worthy terminal card summarising the memory brain:
 memories / skills / playbooks stored, the simulated context-token savings
 percentage, repeated-failure rate improvement, and hotspot coverage.

 Token-ROI numbers come from the same deterministic bench harness as
 ``onmc bench`` — no LLM is called.  Results are identical across runs on
 the same memory store.  Use ``--json`` for machine-readable output.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON to stdout.                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc sbom`

```text
Usage: onmc sbom [OPTIONS]

 Generate a CycloneDX 1.5 SBOM of this project's dependencies.

 Reads ``uv.lock`` (preferred, fully pinned) or falls back to
 ``pyproject.toml`` when no lockfile is present.  Output is
 deterministic: components are sorted alphabetically by name.

 Pure stdlib — no network calls, no new dependencies.

 Examples:

     onmc sbom                       # print to stdout

     onmc sbom --out sbom.json       # write to file

     onmc sbom --json                # onmc envelope (pipeline-friendly)

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --out         FILE  Write the SBOM to FILE instead of stdout.                │
│ --json              Wrap the CycloneDX document in an onmc JSON envelope     │
│                     {"kind": "sbom", "sbom": {...}} for pipeline             │
│                     composition.                                             │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc scorecard`

```text
Usage: onmc scorecard [OPTIONS]

 One shareable agent-readiness + trust scorecard for this repo.

 Aggregates four onmc signals — agent-readiness (roast), top-agent trust
 (registry), best-verified model (flywheel), and institutional-memory
 coverage (orggraph) — into a single card. Deterministic and offline. Any
 unavailable signal degrades to "n/a" with a note; the command always
 exits 0.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json              Emit the scorecard as a JSON object.                     │
│ --markdown          Emit the shareable Markdown scorecard block.             │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc selfimprove`

```text
Usage: onmc selfimprove [OPTIONS] COMMAND [ARGS]...

 After-turn learning review -- extract durable learnings from a transcript and
 propose memory updates for human approval.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ review  Extract candidate learnings from a transcript and rank them.         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc selfimprove review`

```text
Usage: onmc selfimprove review [OPTIONS]

 Extract candidate learnings from a transcript and rank them.

 Reads from FILE (``--from-file``) or stdin. Scans for user corrections,
 stated preferences, and confirmed conventions using pure heuristics -- no
 LLM calls, no network.

 With ``--stage`` each candidate is pushed into the memstage pending queue
 so a human can review and approve via ``onmc memstage approve``.

 Examples:

     onmc selfimprove review --from-file session.txt

     onmc selfimprove review --from-file session.txt --json

     onmc selfimprove review --from-file session.txt --stage

     cat session.txt | onmc selfimprove review

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --from-file        FILE  Read transcript text from FILE instead of stdin.    │
│ --json                   Wrap output in a JSON envelope {"kind":             │
│                          "selfimprove", "candidates": [...]} for pipeline    │
│                          composition.                                        │
│ --stage                  Push each candidate into the memstage pending queue │
│                          (human approves via ``onmc memstage approve``).     │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc serve`

```text
Usage: onmc serve [OPTIONS]

 Serve ONMC over the requested runtime protocol.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --mcp               Run the ONMC MCP server over stdio.                      │
│ --repo        TEXT  Repository path to serve (resolved once at startup).     │
│                     [default: .]                                             │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc session-search`

```text
Usage: onmc session-search [OPTIONS] QUERY

 Full-text search across all of onmc's persisted history.

 Searches memories, attempts, tasks, and memory_artifacts using SQLite's
 FTS5 engine (falls back to LIKE when FTS5 is absent).  Results are ranked
 by BM25 relevance and include a short snippet showing the match context.

 Complements ``onmc recall`` (semantic KNN over curated memories) by
 covering the complete history with keyword search.

 Examples:

     onmc session-search "cache invalidation"

     onmc session-search "auth bug" --limit 5

     onmc session-search "migration" --json

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    query      TEXT  Search query.  All alphanumeric tokens are matched (OR │
│                       logic).                                                │
│                       [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --limit  -n      INTEGER RANGE [1<=x<=500]  Maximum number of results to     │
│                                             return.                          │
│                                             [default: 20]                    │
│ --json                                      Emit results as a JSON envelope  │
│                                             {"kind": "session-search",       │
│                                             "query": "...", "hits": [...]}   │
│                                             for pipeline composition.        │
│ --help                                      Show this message and exit.      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc setup`

```text
Usage: onmc setup [OPTIONS]

 Run the interactive ONMC onboarding wizard.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --yes             Use defaults and skip interactive prompts.                 │
│ --no-llm          Skip provider setup and LLM-assisted extraction.           │
│ --help            Show this message and exit.                                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc skill`

```text
Usage: onmc skill [OPTIONS] COMMAND [ARGS]...

 Manage self-improving skills synthesized from playbooks and memory patterns.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ promote   Promote a playbook or recurring patterns to skill(s).              │
│ list      List all persisted skills.                                         │
│ show      Show a single skill with body, trigger, and metadata.              │
│ feedback  Apply a trust signal to a stored skill.                            │
│ prune     Disable auto_inject on low-success, long-unused skills.            │
│ export    Export skills as Agent Skills SKILL.md files (agentskills.io       │
│           standard).                                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc skill export`

```text
Usage: onmc skill export [OPTIONS]

 Export skills as Agent Skills SKILL.md files (agentskills.io standard).

 Writes one <slug>/SKILL.md per skill.  The output is compatible with
 Claude Code, Cursor, Codex, Gemini, Copilot, OpenCode, Goose, Letta,
 Hermes, and 16+ other tools that support the agentskills.io open standard.


 Examples
 --------
 onmc skill export
 onmc skill export --out .claude/skills
 onmc skill export --scope personal
 onmc skill export --json

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --out          PATH  Output directory (default: .claude/skills/).            │
│ --scope        TEXT  'project' (default) → .claude/skills/; 'personal' →     │
│                      ~/.claude/skills/.                                      │
│                      [default: project]                                      │
│ --json               Emit list of written paths as JSON.                     │
│ --help               Show this message and exit.                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc skill feedback`

```text
Usage: onmc skill feedback [OPTIONS] SKILL_ID DIRECTION

 Apply a trust signal to a stored skill.

 'up' marks the skill as having helped and nudges its confidence upward.
 'down' records the usage without incrementing success_count and nudges
 confidence downward (clamped at a floor so the skill remains visible).


 Examples
 --------
 onmc skill feedback sk_abc123 up
 onmc skill feedback sk_abc123 down
 onmc skill feedback sk_abc123 up --json

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    skill_id       TEXT  Skill ID to apply feedback to. [required]          │
│ *    direction      TEXT  Trust signal: 'up' (helped) or 'down' (did not     │
│                           help).                                             │
│                           [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the updated skill as JSON.                              │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc skill list`

```text
Usage: onmc skill list [OPTIONS]

 List all persisted skills.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit skills as JSON array.                                   │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc skill promote`

```text
Usage: onmc skill promote [OPTIONS] [PLAYBOOK_ID]

 Promote a playbook or recurring patterns to skill(s).

 Provide a playbook ID to lift a single playbook into a named, reusable
 skill.  Use --auto to scan all stored memories for recurring fail→fix
 patterns and high-signal tag clusters, promoting each to a skill.


 Examples
 --------
 onmc skill promote pb_abc123
 onmc skill promote pb_abc123 --name "Cache Invalidation"
 onmc skill promote --auto
 onmc skill promote --auto --json

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   [playbook_id]      TEXT  Playbook ID (or prefix) to promote to a skill.    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --auto              Auto-detect recurring patterns and promote all.          │
│ --name        TEXT  Override the skill name (only used with a playbook-id).  │
│ --json              Emit the new skill(s) as JSON.                           │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc skill prune`

```text
Usage: onmc skill prune [OPTIONS]

 Disable auto_inject on low-success, long-unused skills.

 A skill is pruned when it has been used at least 3 times with a success
 rate below 30%, or has not been used in the last 60 days.  Pruning sets
 auto_inject=False so the injection layer skips it; the skill remains in
 storage and can be re-examined or deleted manually.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit pruned skills as JSON array.                            │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc skill show`

```text
Usage: onmc skill show [OPTIONS] SKILL_ID

 Show a single skill with body, trigger, and metadata.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    skill_id      TEXT  Skill ID (or prefix) to show. [required]            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the skill as JSON.                                      │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc skillguard`

```text
Usage: onmc skillguard [OPTIONS] COMMAND [ARGS]...

 Skill write-approval gate: propose skill create/edit/delete, review diffs,
 then approve or reject — nothing lands in the skill store without your
 sign-off.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ stage    Stage a proposed skill change into the pending queue.               │
│ list     List pending proposals with ids and one-line gists.                 │
│ diff     Show a unified diff of the proposed skill change.                   │
│ approve  Approve a pending proposal and apply it to the skill store.         │
│ reject   Reject a pending proposal: drop it and keep an audit trail.         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc skillguard approve`

```text
Usage: onmc skillguard approve [OPTIONS] PROPOSAL_ID

 Approve a pending proposal and apply it to the skill store.

 The approved change is written via the real skill storage path so it
 lands with full provenance. The proposal is then removed from the
 pending queue and an audit record is written under
 ``.onmc/skillguard/audit/``.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    proposal_id      TEXT  Proposal id to approve (from 'onmc skillguard    │
│                             list').                                          │
│                             [required]                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the audit record as JSON.                               │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc skillguard diff`

```text
Usage: onmc skillguard diff [OPTIONS] PROPOSAL_ID

 Show a unified diff of the proposed skill change.

 Compares the current skill body (or an empty baseline for new skills)
 against the proposed content. ``+`` lines would be added on approve;
 ``-`` lines would be removed.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    proposal_id      TEXT  Proposal id to diff (from 'onmc skillguard       │
│                             list').                                          │
│                             [required]                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc skillguard list`

```text
Usage: onmc skillguard list [OPTIONS]

 List pending proposals with ids and one-line gists.

 Shows proposals in queue order (by seq). Each line contains the
 proposal id, operation, and skill name. Use ``diff <id>`` to see the
 full unified diff.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit pending proposals as JSON.                              │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc skillguard reject`

```text
Usage: onmc skillguard reject [OPTIONS] PROPOSAL_ID

 Reject a pending proposal: drop it and keep an audit trail.

 The proposal is removed from the pending queue. An audit record is
 written under ``.onmc/skillguard/audit/`` so the decision is traceable.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    proposal_id      TEXT  Proposal id to reject (from 'onmc skillguard     │
│                             list').                                          │
│                             [required]                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --reason        TEXT  Why this proposal is being rejected.                   │
│ --json                Emit the audit record as JSON.                         │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc skillguard stage`

```text
Usage: onmc skillguard stage [OPTIONS]

 Stage a proposed skill change into the pending queue.

 The change is NOT applied to the skill store — it waits in the queue
 until you run ``approve`` or ``reject``. Review the diff first with
 ``onmc skillguard diff <id>``.

 Exactly one of ``--content`` or ``--content-file`` must be supplied for
 create/edit operations.  For delete, both may be omitted.

 Examples:

     onmc skillguard stage --name "my-pattern" --op create \
       --content "Always prefer uv over pip" --reason "team convention"

     onmc skillguard stage --name "my-pattern" --op edit \
       --content-file updated_skill.md

     onmc skillguard stage --name "old-pattern" --op delete \
       --reason "obsolete since v2 migration"

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --name                TEXT  Name of the skill to create, edit, or delete. │
│                                [required]                                    │
│ *  --op                  TEXT  Operation to propose: create, edit, or        │
│                                delete.                                       │
│                                [required]                                    │
│    --content             TEXT  Proposed skill body (inline string). Mutually │
│                                exclusive with --content-file.                │
│    --content-file        FILE  Path to a file whose contents become the      │
│                                proposed skill body.                          │
│    --reason              TEXT  Why this skill change is being proposed.      │
│    --json                      Emit the staged proposal as JSON.             │
│    --help                      Show this message and exit.                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc solve`

```text
Usage: onmc solve [OPTIONS]

 Compile repo-aware context and ask the configured LLM for the next best
 approach.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --task           TEXT  Engineering task to solve. [required]              │
│    --task-id        TEXT  Optional existing task to link this output to.     │
│    --no-llm               Use heuristic fallback instead of the configured   │
│                           LLM.                                               │
│    --help                 Show this message and exit.                        │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc spec`

```text
Usage: onmc spec [OPTIONS] COMMAND [ARGS]...

 Inspect and validate the Agent Memory open spec.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ print     Print the Agent Memory Spec version and schema summary.            │
│ validate  Validate that a .agent-memory/ directory conforms to the open      │
│           spec.                                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc spec print`

```text
Usage: onmc spec print [OPTIONS]

 Print the Agent Memory Spec version and schema summary.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc spec validate`

```text
Usage: onmc spec validate [OPTIONS]

 Validate that a .agent-memory/ directory conforms to the open spec.

 Checks manifest presence and field completeness, validates all memory and
 task record files, and verifies enum values against the spec. Exits with
 code 1 if any errors are found.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --path        PATH  Path to the .agent-memory/ directory to validate.        │
│                     Defaults to .agent-memory/ in the current repo root.     │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc status`

```text
Usage: onmc status [OPTIONS]

 Show local ONMC status.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc statusline`

```text
Usage: onmc statusline [OPTIONS]

 Print a compact one-line brain health string for Claude Code statusLine.

 Example output: 🧠 142 mem · 87% fresh · 3 stale · 12k tok/day

 Wire into Claude Code by adding to your settings.json:
   "statusLine": "onmc statusline"

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc swarm`

```text
Usage: onmc swarm [OPTIONS] COMMAND [ARGS]...

 Parallel accountable agent loops — a bounded pool of run_loop workers. Honest:
 'many tasks' = a queue drained by min(cpu-1, 8) workers, not unlimited
 simultaneous agents.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ run     Run a parallel swarm of accountable agent loops.                     │
│ plan    Allocate an IN-SESSION (subagent) swarm — token-free fan-out.        │
│ record  Record one finished inline unit: write a receipt + update the        │
│         manifest.                                                            │
│ verify  Run the HONEST per-unit quality gate in the unit's OWN worktree.     │
│ pr      Open the unit's OWN pull request (push branch + ``gh pr create``).   │
│ status  Show status of a swarm or all swarms.                                │
│ list    List all known swarm runs.                                           │
│ abort   Request graceful abort of a swarm or all swarms.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc swarm abort`

```text
Usage: onmc swarm abort [OPTIONS] [SWARM_ID]

 Request graceful abort of a swarm or all swarms.

 Writes an ABORT sentinel file.  Running units finish their current
 iteration then stop; queued units never start.  This is graceful —
 in-progress agent subprocesses are not forcibly killed.


 Examples
 --------
 onmc swarm abort abc123ef
 onmc swarm abort --all

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   [swarm_id]      TEXT  Swarm ID to abort.  Omit when using --all.           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --all           Abort ALL running swarms by writing a global ABORT file.     │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc swarm list`

```text
Usage: onmc swarm list [OPTIONS]

 List all known swarm runs.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit list as JSON.                                           │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc swarm plan`

```text
Usage: onmc swarm plan [OPTIONS]

 Allocate an IN-SESSION (subagent) swarm — token-free fan-out.

 This does NOT spawn any process or call any model.  It allocates a swarm id
 + manifest and returns the unit list and abort-sentinel path.  Claude Code
 then fans subagents out itself (the subagents inherit the session's auth, so
 NO API key/token is needed), and reports each unit back via
 ``onmc swarm record``.  Use ``onmc swarm status/list/abort`` exactly as for
 process swarms.


 Examples
 --------
 onmc swarm plan --file tasks.txt --json
 onmc swarm plan --task "audit module A" --task "audit module B" --json

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --task               TEXT                  Goal text for one unit.  Repeat   │
│                                            for multiple.                     │
│ --file               PATH                  Text file: one task goal per      │
│                                            non-empty line.                   │
│ --concurrency        INTEGER RANGE [x>=1]  Recommended fan-out width         │
│                                            (advisory; Claude Code caps ~10   │
│                                            subagents).                       │
│ --json                                     Emit the plan as JSON to stdout.  │
│ --help                                     Show this message and exit.       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc swarm pr`

```text
Usage: onmc swarm pr [OPTIONS] SWARM_ID UNIT_ID

 Open the unit's OWN pull request (push branch + ``gh pr create``).

 REFUSES an unverified unit: the unit must be recorded ``done``/verified in
 the manifest first.  PR-and-stop — this never auto-merges.


 Example
 -------
 onmc swarm pr ab12cd34 unit-0000 --worktree /tmp/wt-unit-0000 --base main

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    swarm_id      TEXT  Swarm ID returned by `swarm plan`. [required]       │
│ *    unit_id       TEXT  Unit ID (e.g. unit-0000). [required]                │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --worktree        PATH  The unit's worktree whose branch is pushed.       │
│                            [required]                                        │
│    --base            TEXT  Base branch the PR targets. [default: main]       │
│    --title           TEXT  PR title (defaults to a unit-scoped title).       │
│    --json                  Emit the PR result as JSON.                       │
│    --help                  Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc swarm record`

```text
Usage: onmc swarm record [OPTIONS] SWARM_ID UNIT_ID

 Record one finished inline unit: write a receipt + update the manifest.

 Honest by construction: a unit is ``done`` ONLY when verified; otherwise it
 is ``failed`` (a subagent that produced nothing useful can never be a
 verified success).  The receipt is as auditable as a process unit's (git
 tree/diff SHA, hash chain, reproducibility envelope).

 Without ``--auto-verify`` the caller's ``--verified`` attestation is used
 (back-compatible).  With ``--auto-verify`` the caller's flag is IGNORED and
 the receipt's verified flag reflects the REAL gate result in ``--worktree``
 (preflight + diff): a unit that did not really build or fails the gate is
 recorded ``failed`` even if ``--verified`` was passed.


 Example
 -------
 onmc swarm record ab12cd34 unit-0000 --goal "audit A" \
     --summary "found 2 issues, fixed both" --verified --files src/a.py
 onmc swarm record ab12cd34 unit-0000 --goal "fix X" --summary "done" \
     --auto-verify --worktree /tmp/wt-unit-0000 --base main

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    swarm_id      TEXT  Swarm ID returned by `swarm plan`. [required]       │
│ *    unit_id       TEXT  Unit ID (e.g. unit-0000). [required]                │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --goal                             TEXT                The unit's goal    │
│                                                           text (for the      │
│                                                           receipt).          │
│                                                           [required]         │
│    --summary                          TEXT                What the subagent  │
│                                                           did (recorded in   │
│                                                           the receipt).      │
│    --verified       --not-verified                        Did the unit meet  │
│                                                           its success        │
│                                                           criteria?          │
│                                                           Defaults to NOT    │
│                                                           verified.          │
│                                                           [default:          │
│                                                           not-verified]      │
│    --aborted                                              Mark the unit as   │
│                                                           aborted (cut       │
│                                                           short).            │
│    --cost-usd                         FLOAT RANGE         Optional USD cost  │
│                                       [x>=0.0]            for this unit.     │
│    --tokens                           INTEGER RANGE       Optional token     │
│                                       [x>=0]              count for this     │
│                                                           unit.              │
│    --files                            TEXT                Comma-separated    │
│                                                           list of files the  │
│                                                           unit touched.      │
│    --auto-verify                                          Staff-engineer     │
│                                                           mode: IGNORE       │
│                                                           --verified and set │
│                                                           the receipt's      │
│                                                           verified flag from │
│                                                           the REAL quality   │
│                                                           gate run in        │
│                                                           --worktree.        │
│    --worktree                         PATH                The unit's         │
│                                                           worktree (required │
│                                                           with               │
│                                                           --auto-verify).    │
│    --base                             TEXT                Base ref the       │
│                                                           unit's diff is     │
│                                                           taken against.     │
│                                                           [default: main]    │
│    --json                                                 Emit the recorded  │
│                                                           result as JSON.    │
│    --help                                                 Show this message  │
│                                                           and exit.          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc swarm run`

```text
Usage: onmc swarm run [OPTIONS]

 Run a parallel swarm of accountable agent loops.

 Each task is one run_loop unit with its own receipt.  Tasks are queued and
 drained by a bounded worker pool (default: min(cpu_count-1, 8) workers).

 HONEST CONCURRENCY: --concurrency N means at most N loops run at the same
 time, NOT N simultaneous agent processes per loop iteration.  API rate
 limits and RAM are the real bottleneck for large N.


 Examples
 --------
 onmc swarm run --task "fix import A" --task "fix import B" --agent claude
 onmc swarm run --file tasks.txt --concurrency 4 --max-cost-usd 5.00
 onmc swarm run --task "lint check" --agent codex --no-isolate --json

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --task                                TEXT                Goal text for one  │
│                                                           swarm unit.        │
│                                                           Repeat for         │
│                                                           multiple tasks.    │
│                                                           Mutually exclusive │
│                                                           with --file.       │
│ --file                                PATH                Path to a text     │
│                                                           file where each    │
│                                                           non-empty line is  │
│                                                           one task goal.     │
│                                                           Mutually exclusive │
│                                                           with --task.       │
│ --agent                               TEXT                Agent CLI: claude  │
│                                                           (default), codex,  │
│                                                           or opencode.       │
│                                                           [default: claude]  │
│ --concurrency                         INTEGER RANGE       Max parallel       │
│                                       [x>=1]              workers.  Default  │
│                                                           min(cpu_count-1,   │
│                                                           8).  HONEST: this  │
│                                                           is a bounded pool  │
│                                                           — not unlimited    │
│                                                           simultaneous       │
│                                                           agents.            │
│ --max-cost-usd                        FLOAT RANGE         Swarm-level total  │
│                                       [x>=0.0]            cost ceiling in    │
│                                                           USD.               │
│ --per-unit-max-it…                    INTEGER RANGE       Per-unit max loop  │
│                                       [x>=1]              iterations.        │
│ --verify                              TEXT                Verify command     │
│                                                           applied to all     │
│                                                           units (default:    │
│                                                           pytest).           │
│ --isolate             --no-isolate                        Run each unit in   │
│                                                           an isolated git    │
│                                                           worktree (default: │
│                                                           True).             │
│                                                           [default: isolate] │
│ --json                                                    Emit full          │
│                                                           SwarmResult as     │
│                                                           JSON to stdout.    │
│ --help                                                    Show this message  │
│                                                           and exit.          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc swarm status`

```text
Usage: onmc swarm status [OPTIONS] [SWARM_ID]

 Show status of a swarm or all swarms.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   [swarm_id]      TEXT  Swarm ID to inspect.  Omit to list all swarms.       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit status as JSON.                                         │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc swarm verify`

```text
Usage: onmc swarm verify [OPTIONS] SWARM_ID UNIT_ID

 Run the HONEST per-unit quality gate in the unit's OWN worktree.

 This is the trust gate: it runs preflight (ruff/mypy/cli-ref/pytest) in
 ``--worktree`` and verifies the unit's diff is real + lawful.  A unit that
 didn't really build (empty diff) or fails the gate CANNOT pass — the command
 exits nonzero when the verdict is not ``ok``.


 Example
 -------
 onmc swarm verify ab12cd34 unit-0000 --worktree /tmp/wt-unit-0000 --base main

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    swarm_id      TEXT  Swarm ID returned by `swarm plan`. [required]       │
│ *    unit_id       TEXT  Unit ID (e.g. unit-0000). [required]                │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --worktree        PATH  The unit's worktree to run the quality gate in.   │
│                            [required]                                        │
│    --base            TEXT  Base ref the unit's diff is taken against.        │
│                            [default: main]                                   │
│    --json                  Emit the verdict as JSON.                         │
│    --help                  Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc sync`

```text
Usage: onmc sync [OPTIONS]

 Export, restore, or hook git-portable ONMC memory state.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --commit                Export to .agent-memory/.                            │
│ --restore               Restore from .agent-memory/.                         │
│ --install-hook          Install a post-commit sync hook.                     │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc task`

```text
Usage: onmc task [OPTIONS] COMMAND [ARGS]...

 Manage task lifecycle state.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ start   Create and activate a new task for the current repository.           │
│ list    List tasks for the current repository.                               │
│ show    Show a stored task with lifecycle details.                           │
│ end     End a task with a terminal status and final summary.                 │
│ status  Update task status.                                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc task end`

```text
Usage: onmc task end [OPTIONS] TASK_ID

 End a task with a terminal status and final summary.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    task_id      TEXT  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --summary        TEXT                        Final task summary.          │
│                                                 [required]                   │
│    --status         [open|active|blocked|solve  Terminal task status.        │
│                     d|abandoned]                [default: solved]            │
│    --help                                       Show this message and exit.  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc task list`

```text
Usage: onmc task list [OPTIONS]

 List tasks for the current repository.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc task show`

```text
Usage: onmc task show [OPTIONS] TASK_ID

 Show a stored task with lifecycle details.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    task_id      TEXT  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc task start`

```text
Usage: onmc task start [OPTIONS]

 Create and activate a new task for the current repository.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --title              TEXT  Short task title. [required]                   │
│ *  --description        TEXT  Task description. [required]                   │
│    --label              TEXT  Repeat to attach one or more labels.           │
│    --help                     Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc task status`

```text
Usage: onmc task status [OPTIONS] TASK_ID

 Update task status.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    task_id      TEXT  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --status        [open|active|blocked|solved  New task status. [required]  │
│                    |abandoned]                                               │
│    --help                                       Show this message and exit.  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc teach`

```text
Usage: onmc teach [OPTIONS]

 Compile repo-aware teaching context and generate a learning artifact.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --task               TEXT  Task to explain and teach from. [required]     │
│    --task-id            TEXT  Optional existing task to link this output to. │
│    --interactive              Enter a follow-up Q&A loop after the initial   │
│                               output.                                        │
│    --no-llm                   Use heuristic fallback instead of the          │
│                               configured LLM.                                │
│    --help                     Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc timeline`

```text
Usage: onmc timeline [OPTIONS]

 Tell this repo's evolution story from its brain.

 Orders the durable memory (decisions, invariants, gotchas, dead-ends)
 over time into a readable narrative grouped into periods. Deterministic
 and offline. An empty brain prints a 'no history yet' note and exits 0.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --since           TEXT  Only include milestones on/after this point — an ISO │
│                         date (2026-07-01) or a relative window (30d).        │
│ --group           TEXT  Period granularity: 'day' or 'week'. [default: day]  │
│ --json                  Emit the timeline as JSON.                           │
│ --markdown              Emit the timeline as a markdown story.               │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc trace`

```text
Usage: onmc trace [OPTIONS] COMMAND [ARGS]...

 Agent Trace Observatory — instrument a session and get a token-ROI report.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ start   Start a new trace session.                                           │
│ stop    Close the current trace session.                                     │
│ report  Show the Agent Trace Observatory token-ROI card for a session.       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc trace report`

```text
Usage: onmc trace report [OPTIONS] [SESSION_ID]

 Show the Agent Trace Observatory token-ROI card for a session.

 Renders a screenshot-worthy terminal card with: estimated token savings,
 repeated reads blocked, tool call stats, memory hit-rate, and loop signals.

 Token-savings estimates are labelled (est) — derived from the bench harness,
 not live LLM measurement.  Use --json for machine-readable output.
 Use --otel <file> to dump OpenTelemetry GenAI-convention span JSON.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   [session_id]      TEXT  Session ID to report on.  Defaults to the current  │
│                           active session.                                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json              Print machine-readable JSON to stdout.                   │
│ --otel        FILE  Write OpenTelemetry GenAI span JSON to this file path.   │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc trace start`

```text
Usage: onmc trace start [OPTIONS]

 Start a new trace session.

 Creates a JSONL session file under .onmc/traces/ and sets the active
 session pointer.  Run 'onmc trace stop' to close the session and then
 'onmc trace report' to view the results.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --label  -l      TEXT  Human-readable label for this session.                │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc trace stop`

```text
Usage: onmc trace stop [OPTIONS]

 Close the current trace session.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc tui`

```text
Usage: onmc tui [OPTIONS]

 Open the interactive terminal brain-browser for memory curation.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc twin`

```text
Usage: onmc twin [OPTIONS] COMMAND [ARGS]...

 Rehearse a code change offline: predict blast radius, surface covering tests,
 flag high-risk touches. Analysis only — never runs or edits code.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ plan      Predict the blast radius of touching PATHS — before you edit.      │
│ rehearse  Rehearse touching PATHS with an explicit before-you-edit advisory. │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc twin plan`

```text
Usage: onmc twin plan [OPTIONS] PATHS...

 Predict the blast radius of touching PATHS — before you edit.

 Offline analysis against the structural code graph: per file, shows how many
 files depend on it, its risk level, and the tests that cover it, plus a
 suggested test command.  Never runs or edits any code.  If the graph is
 empty, run `onmc codegraph` first.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    paths...      TEXT  Repo-relative (or absolute) files you intend to     │
│                          edit.                                               │
│                          [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the rehearsal plan as JSON.                             │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc twin rehearse`

```text
Usage: onmc twin rehearse [OPTIONS] PATHS...

 Rehearse touching PATHS with an explicit before-you-edit advisory.

 Same blast-radius table as `twin plan`, plus a spelled-out summary: which
 tests to run first, how many dependents to watch, and any HIGH-RISK hub
 files.  Pure analysis — nothing is executed or edited.  If the graph is
 empty, run `onmc codegraph` first.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    paths...      TEXT  Repo-relative (or absolute) files you intend to     │
│                          edit.                                               │
│                          [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the rehearsal plan as JSON.                             │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc ui`

```text
Usage: onmc ui [OPTIONS]

 Open the local read-only ONMC visual dashboard.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --host                   TEXT                      Dashboard bind address.   │
│                                                    [default: 127.0.0.1]      │
│ --port                   INTEGER RANGE             Dashboard TCP port.       │
│                          [0<=x<=65535]             [default: 8765]           │
│ --open      --no-open                              Open the dashboard in a   │
│                                                    browser.                  │
│                                                    [default: open]           │
│ --export                 PATH                      Write a standalone HTML   │
│                                                    snapshot instead of       │
│                                                    serving.                  │
│ --help                                             Show this message and     │
│                                                    exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc unwrap`

```text
Usage: onmc unwrap [OPTIONS]

 Remove the onmc wrap layer — the perfect inverse of ``onmc wrap``.

 Strips exactly the two wrap hooks, the wrap-state file, and the
 CLAUDE.md policy stanza. Every other hook and all CLAUDE.md content is
 left untouched. The settings.json backup is kept as a safety artifact.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --global    --project      Remove from the user-level                        │
│                            ~/.claude/settings.json (default: project).       │
│                            [default: project]                                │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc user`

```text
Usage: onmc user [OPTIONS] COMMAND [ARGS]...

 Manage cross-repo user preferences (stored in ~/.onmc, not repo-scoped).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ add     Add a cross-repo user preference (stored in ~/.onmc, not             │
│         git-tracked).                                                        │
│ list    List all cross-repo user preferences.                                │
│ show    Show a single user preference by ID.                                 │
│ remove  Remove a user preference by ID.                                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc user add`

```text
Usage: onmc user add [OPTIONS]

 Add a cross-repo user preference (stored in ~/.onmc, not git-tracked).

 User preferences travel with you across all repositories and appear at the
 top of every session boot digest so your coding style is always applied.
 Examples: "always use pytest", "run ruff before committing".

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --title          TEXT  Short preference title. [required]                 │
│ *  --summary        TEXT  Full description of the preference or              │
│                           working-style fact.                                │
│                           [required]                                         │
│    --help                 Show this message and exit.                        │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc user list`

```text
Usage: onmc user list [OPTIONS]

 List all cross-repo user preferences.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc user remove`

```text
Usage: onmc user remove [OPTIONS] MEMORY_ID

 Remove a user preference by ID.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    memory_id      TEXT  [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc user show`

```text
Usage: onmc user show [OPTIONS] MEMORY_ID

 Show a single user preference by ID.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    memory_id      TEXT  [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc verify-diff`

```text
Usage: onmc verify-diff [OPTIONS]

 Adversarially verify the working diff against a base ref.

 Passes ONLY when the change is real (non-empty), introduces every expected
 symbol/file, and is lawful (no banned or secret patterns in added lines).
 Designed to close the empty-diff false-converge: a passing test suite over
 an unchanged tree must NOT count as success.  With ``--structural`` and the
 ``difft`` binary installed, it also rejects reformat-only diffs.

 Exit codes:

 - 0 — every check passed
 - 1 — one or more checks failed

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --base                 TEXT  Git ref to diff against (default: main).        │
│                              [default: main]                                 │
│ --expect-symbol        TEXT  Symbol that must appear in added lines.         │
│                              Repeatable.                                     │
│ --expect-file          TEXT  Repo-relative path that must receive added      │
│                              lines.  Repeatable.                             │
│ --structural                 Use difftastic (the 'difft' binary) for a       │
│                              structural/AST diff that ignores formatting     │
│                              noise.  No-op when 'difft' is not on PATH       │
│                              (falls back to line-diff).                      │
│ --json                       Emit the full VerifyReport as JSON to stdout.   │
│ --help                       Show this message and exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc viz`

```text
Usage: onmc viz [OPTIONS] COMMAND [ARGS]...

 Render onmc graphs as shareable diagrams (Mermaid or D2, no server, no dep).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ memory  Print the memory relationship graph as a diagram.                    │
│ code    Print the code-graph blast radius of *target* as a diagram.          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc viz code`

```text
Usage: onmc viz code [OPTIONS] TARGET

 Print the code-graph blast radius of *target* as a diagram.

 The target file(s) sit in the centre; importers/dependents flow in, the
 target's own imports flow out, and related tests are shown as a group.
 Use ``--format d2`` for D2 (terrastruct.com/d2) output instead of the
 default Mermaid ``graph TD``. Deterministic and offline.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    target      TEXT  Repo-relative file path or bare symbol name to graph  │
│                        the blast radius of.                                  │
│                        [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                        Wrap the diagram text in a JSON envelope.      │
│ --format        [mermaid|d2]  Output diagram format: mermaid (default) or    │
│                               d2.                                            │
│                               [default: mermaid]                             │
│ --help                        Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc viz memory`

```text
Usage: onmc viz memory [OPTIONS]

 Print the memory relationship graph as a diagram.

 Nodes are memory entries grouped by kind; edges are the recorded
 ``memory_edges`` relationships (supersedes / contradicts / relates /
 duplicate_of). Use ``--format d2`` for D2 (terrastruct.com/d2) output
 instead of the default Mermaid ``graph TD``. Deterministic and offline.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --limit         INTEGER       Maximum number of memory nodes to render (most │
│                               recent first).                                 │
│                               [default: 40]                                  │
│ --json                        Wrap the diagram text in a JSON envelope.      │
│ --format        [mermaid|d2]  Output diagram format: mermaid (default) or    │
│                               d2.                                            │
│                               [default: mermaid]                             │
│ --help                        Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc whip`

```text
Usage: onmc whip [OPTIONS] COMMAND [ARGS]...

 Steer a running agent and record reward signals (the reins + whip control
 surface).

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ nudge     Queue a gentle steering directive for the running agent.           │
│ redirect  Queue a hard course-correction directive for the running agent.    │
│ pending   Show queued directives without consuming them.                     │
│ clear     Consume and discard all queued directives.                         │
│ crack     Record a negative reward signal (correction) for the current agent │
│           run.                                                               │
│ treat     Record a positive reward signal (praise) for the current agent     │
│           run.                                                               │
│ tally     Show the reward signal tally (praises vs corrections per           │
│           goal/agent).                                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc whip clear`

```text
Usage: onmc whip clear [OPTIONS]

 Consume and discard all queued directives.

 After this call ``onmc whip pending`` will show an empty queue.  Use this
 to drain stale directives that are no longer relevant.

 Examples:

     onmc whip clear

     onmc whip clear --json

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit a JSON confirmation envelope.                           │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc whip crack`

```text
Usage: onmc whip crack [OPTIONS]

 Record a negative reward signal (correction) for the current agent run.

 Signals are appended to ``.onmc/whip/rewards.jsonl`` — a schema
 compatible with flywheel receipts so future analysis can learn from
 steering feedback alongside run outcomes.

 Examples:

     onmc whip crack

     onmc whip crack --reason "hallucinated an API that doesn't exist"

     onmc whip crack --goal "add timeout param" --agent my-swarm-unit

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --reason  -r      TEXT  Optional rationale for the correction.               │
│ --goal            TEXT  Override the current goal label (default:            │
│                         'current').                                          │
│                         [default: current]                                   │
│ --agent           TEXT  Agent identifier (default: 'claude').                │
│                         [default: claude]                                    │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc whip nudge`

```text
Usage: onmc whip nudge [OPTIONS] MSG

 Queue a gentle steering directive for the running agent.

 The message is appended to ``.onmc/whip/pending.jsonl`` and delivered
 (in FIFO order, after any pending redirects) when the agent next calls
 ``onmc whip pending`` or ``onmc whip clear``.

 Examples:

     onmc whip nudge "prefer smaller functions"

     onmc whip nudge "add a docstring to each new public method"

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    msg      TEXT  Gentle steering message to queue. [required]             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc whip pending`

```text
Usage: onmc whip pending [OPTIONS]

 Show queued directives without consuming them.

 Directives are shown in priority order: redirects first, then nudges,
 each sub-group in FIFO insertion order.  This command is read-only;
 to consume-and-clear the queue use ``onmc whip clear``.

 Examples:

     onmc whip pending

     onmc whip pending --json

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit directives as a JSON envelope.                          │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc whip redirect`

```text
Usage: onmc whip redirect [OPTIONS] MSG

 Queue a hard course-correction directive for the running agent.

 Redirects have higher priority than nudges: ``onmc whip pending`` and
 ``onmc whip clear`` surface all redirects first (FIFO within the redirect
 group), then nudges (FIFO within the nudge group).

 Examples:

     onmc whip redirect "stop — revert the last edit, it breaks the API
 contract"

     onmc whip redirect "do NOT touch the migration files"

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    msg      TEXT  Hard course-correction message to queue. [required]      │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc whip tally`

```text
Usage: onmc whip tally [OPTIONS]

 Show the reward signal tally (praises vs corrections per goal/agent).

 Aggregates all signals in ``.onmc/whip/rewards.jsonl`` and prints a
 summary table.  With ``--json``, emits a machine-readable envelope for
 pipeline composition or flywheel consumption.

 Examples:

     onmc whip tally

     onmc whip tally --json

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit the reward tally as a JSON envelope.                    │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc whip treat`

```text
Usage: onmc whip treat [OPTIONS]

 Record a positive reward signal (praise) for the current agent run.

 Signals are appended to ``.onmc/whip/rewards.jsonl`` — a schema
 compatible with flywheel receipts so future analysis can learn from
 steering feedback alongside run outcomes.

 Examples:

     onmc whip treat

     onmc whip treat --reason "minimal diff, all tests green"

     onmc whip treat --goal "refactor parser" --agent my-swarm-unit

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --reason  -r      TEXT  Optional rationale for the praise.                   │
│ --goal            TEXT  Override the current goal label (default:            │
│                         'current').                                          │
│                         [default: current]                                   │
│ --agent           TEXT  Agent identifier (default: 'claude').                │
│                         [default: claude]                                    │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc why`

```text
Usage: onmc why [OPTIONS] PATH

 Explain why a file looks the way it does, from memory + git history.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    path      TEXT  File path to explain (repo-relative or absolute).       │
│                      [required]                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --no-llm              Skip the optional LLM narrative; deterministic only.   │
│ --at            TEXT  Bound the git-history section to this commit-ish       │
│                       (hash, tag, or branch). Memory entries reflect the     │
│                       current store and are NOT time-bounded.                │
│ --terse               Emit compact terse output (overrides ONMC_TERSE env    │
│                       var).                                                  │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc wiki`

```text
Usage: onmc wiki [OPTIONS] COMMAND [ARGS]...

 Generate wiki and knowledge-graph exports from stored memory.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --output        PATH                 Directory to write wiki pages into.     │
│                                      Defaults to .onmc/wiki/ (gitignored).   │
│                                      Pass e.g. docs/wiki to produce a        │
│                                      committable copy.                       │
│ --format        [markdown|obsidian]  Output format: markdown wiki or         │
│                                      Obsidian vault.                         │
│                                      [default: markdown]                     │
│ --help                               Show this message and exit.             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ logseq  Export memory as a Logseq-compatible knowledge graph.                │
│ foam    Export memory as a Foam-compatible markdown knowledge graph.         │
│ site    Export memory as a self-contained static HTML site.                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc wiki foam`

```text
Usage: onmc wiki foam [OPTIONS]

 Export memory as a Foam-compatible markdown knowledge graph.

 Writes one markdown note per memory into a ``notes/`` subdirectory and an
 ``index.md`` entry point, using YAML frontmatter and ``[]`` for
 memory edges.  No new dependency — pure stdlib string generation.

 Foam is a VS Code extension that reads a flat directory of markdown notes
 and renders an interactive knowledge graph.  The output directory defaults
 to ``.onmc/foam/`` and can be opened directly in VS Code with the Foam
 extension installed.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --out         PATH  Directory to write Foam notes into. Defaults to          │
│                     .onmc/foam/ (gitignored).                                │
│ --json              Print a JSON envelope listing written paths.             │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc wiki logseq`

```text
Usage: onmc wiki logseq [OPTIONS]

 Export memory as a Logseq-compatible knowledge graph.

 Writes one markdown page per memory into a ``pages/`` subdirectory, using
 Logseq's ``key:: value`` page properties and ``[]`` for memory
 edges.  No new dependency — pure stdlib string generation.

 The output directory defaults to ``.onmc/logseq/`` and is safe to open
 directly in the Logseq desktop app as a graph folder.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --out         PATH  Directory to write Logseq pages into. Defaults to        │
│                     .onmc/logseq/ (gitignored).                              │
│ --json              Print a JSON envelope listing written paths.             │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc wiki site`

```text
Usage: onmc wiki site [OPTIONS]

 Export memory as a self-contained static HTML site.

 Writes ``index.html`` listing all memories grouped by kind, plus one
 ``<slug>.html`` detail page per memory with its full body and resolved
 ``<a href>`` links for memory edges.  No external app, no JS framework,
 no network required — open ``index.html`` directly in any browser.

 The output directory defaults to ``.onmc/site/``.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --out         PATH  Directory to write the HTML site into. Defaults to       │
│                     .onmc/site/ (gitignored).                                │
│ --json              Print a JSON envelope listing written paths.             │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc wrap`

```text
Usage: onmc wrap [OPTIONS]

 Make onmc the default layer for Claude Code in this repo.

 Installs a Task intercept (PreToolUse matcher ``Task``) that redirects
 native agent-spawning to ``onmc swarm``, plus a prompt router
 (UserPromptSubmit) that nudges toward onmc paths. Backs up
 settings.json before editing. Reverse with ``onmc unwrap``.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --strict    --soft         strict: deny native Task spawns and redirect to   │
│                            `onmc swarm`. soft: allow them with a nudge.      │
│                            Default: strict.                                  │
│                            [default: strict]                                 │
│ --global    --project      Install into the user-level                       │
│                            ~/.claude/settings.json (default: project).       │
│                            [default: project]                                │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```
