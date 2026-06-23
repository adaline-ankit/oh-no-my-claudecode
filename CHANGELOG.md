# Changelog

All notable changes to this project are documented here.

## [Unreleased]

## [0.35.0] — 2026-06-24

### Added

- **`onmc replay` — replay lab.** Completes the proof trilogy (benchmark proves value, eval gates regressions, replay shows what memory changed). Consumes a recorded `onmc trace` session (`.onmc/traces/<id>.jsonl`) and deterministically re-derives what the brain would surface at each step — recall hits, guard dead-ends, injected context chars — with no LLM or network. `onmc replay run <session-id-or-path> [--json]` for the per-step report; `--compare` runs with-vs-without-memory and reports "memory would have changed N of M steps"; `--without-memory` for the cold baseline. Resolves a session by id or direct JSONL path.

## [0.34.0] — 2026-06-24

### Added

- **Tamper-evident loop run receipt + proof-based completion (P1 accountability core).** After every real `onmc loop` run, onmc writes a tamper-evident receipt to `.agent-memory/receipts/`: goal, agent, model, `verified`, stop_reason, iterations, tokens/cost/wall, verifier command + final exit code, git tree SHA, diff SHA, loop-spec SHA, output digest, onmc version — bound by a SHA-256 hash chain across iterations (not signed yet). `verified` is true only when the loop converged AND the final verifier passed — never because the model claimed "done". The CLI prints a VERIFIED / NOT-VERIFIED block + receipt path; `--json` embeds the receipt.
- **Hard cost & wall-time limits:** `onmc loop --max-cost-usd` and `--max-wall-seconds` (deterministic, stop_reason `cost` / `wall-time`), alongside the existing token-budget / max-iterations / no-progress stops. Per-iteration cost is read from the Claude adapter output.

## [0.33.0] — 2026-06-23

### Added

- **`onmc mcp` — runtime MCP trust gateway.** The runtime complement to the static `onmc audit`: audit finds risky config, this gates risky calls. A `.onmc/mcp-policy.yaml` declares a server allowlist, per-tool scopes (read/write/network), and an approval-required list; `classify_call` returns allow / block / approval_required per tool call (secret-in-args → block; unknown server/network/write → approval; reuses the `onmc audit` secret + prompt-injection patterns on args). `onmc mcp policy init [--force]` writes a documented safe-default policy; `onmc mcp check <calls.jsonl> [--json] [--fail-on block|approval_required]` classifies recorded tool calls offline and exits nonzero at/above the threshold for CI/guard gating, appending decisions to a JSONL audit log.

## [0.32.0] — 2026-06-23

### Added

- **`onmc loop` now drives a real agent (P0 of the accountable-loops direction).** Replaced the stub runner that returned "[no agent configured]" with real headless adapters behind one injectable interface: `ClaudeCliAdapter` (`claude -p --output-format json`, defensive token/cost parse) and `CodexCliAdapter` (`codex exec`). `files_touched` is computed from real before/after `git status`; tokens/cost come from the agent's own output (never fabricated). `onmc loop --agent claude|codex`; the `--dry-run` path stays subprocess-free and a missing agent binary degrades cleanly. Cross-agent by design (headless CLI, no SDK lock-in).

## [0.31.0] — 2026-06-23

### Added

- **`onmc gh-aw init` — memory-aware GitHub Actions workflow pack.** Scaffolds 4 agentic workflows into `.github/workflows/onmc-*.yml` (rides the github/gh-aw trend): issue opened → `recall`/`guard` posts related failures + decisions; PR opened → `blame`/`guard`/`audit` posts blast-radius + related memories + a security check; PR merged → `mine` records the outcome so future agents learn; weekly cron → opens a stale-memory audit issue. Safe by default (read-only default permissions, comment-only safe-outputs, pinned action SHAs, plain `pull_request`, no `curl|bash`, no inline secrets). Idempotent (skip existing unless `--force`); `--dry-run` previews. `onmc gh-aw init [PATH] [--dry-run] [--force] [--json]`.

## [0.30.0] — 2026-06-23

### Added

- **`onmc eval` — memory evaluation + regression gate.** Proves the brain helps and blocks regressions in CI (the 2026 evals trend). An eval case is a query + expected memory behavior, scored with onmc's own retrieval: correct-files-surfaced (`compile_recall` top-K hit) and failed-path-avoided (`compile_guard` surfaces the known dead-end), plus injected cost. Running with-memory vs without-memory yields a measurable score delta. `onmc eval create --from-task <id>` (cases stored as JSON under `.onmc/evals/`), `onmc eval run [--without-memory] [--fail-under <pct>] [--json]`, `onmc eval compare [--baseline <pct>] [--json]`; `--fail-under`/`--baseline` exit nonzero below threshold so it drops into CI as a regression gate. Deterministic, offline, no LLM, no schema migration.

## [0.29.0] — 2026-06-23

### Added

- **`onmc audit` — agent-config security scorecard.** Scans a repo's agent configuration (CLAUDE.md/AGENTS.md, `.claude/settings.json`, `.mcp.json`, hooks) for the 2026 top agent-safety risks and emits a scored, CI-gateable report. 11 rules across over-broad permissions, hook-injection, risky MCP servers, secret detection, and prompt-injection surface — each finding carries a concrete fix. Score = 100 − Σ severity weights → grade A–F. `onmc audit [PATH] [--json] [--fail-on critical|high|medium|low]` exits nonzero at/above the threshold (default high) so it drops into CI. Deterministic, no network, no LLM.

## [0.28.0] — 2026-06-23

### Added

- **`onmc benchmark` — a reproducible memory-effectiveness suite.** One verifiable command, every metric labelled MEASURED (live, no LLM) vs SIM (deterministic model). MEASURED: brain composition, recall latency p50/p95 + hits/query, terse-vs-verbose injection char reduction, TOON-vs-JSON payload reduction. SIM: repeated-failure rate −100%, wasted attempts −9, context tokens −97%, tasks +0 (reuses the canonical `onmc bench` harness). Injectable timer keeps timing tests deterministic; graceful on small brains. `onmc benchmark [--runs N] [--json]`.

## [0.27.0] — 2026-06-23

### Added

- **`onmc trace` — Agent Trace Observatory.** `onmc trace start|stop|report` instruments an agent session and produces a shareable token-ROI card: headline "saved X% (est)", tokens used vs estimated-without-onmc, repeated file reads blocked, tool calls/failures, memory hit-rate, and loop detection. Reuses the existing notify/firewall JSONL event stream (no second event bus) plus a session-scoped `.onmc/traces/<id>.jsonl`. `compile_trace_report` is pure + deterministic with estimates honestly labelled `(est)`. `--json` for machine output; `--otel <file>` emits OpenTelemetry GenAI (`gen_ai.*`) span dicts with zero SDK dependency.

## [0.26.0] — 2026-06-23

### Added

- **`onmc loop` — a memory-grounded SOTA autonomous loop.** A ralph-style loop that doesn't repeat itself: each iteration recalls prior dead-ends (`compile_guard`) and injects a "KNOWN DEAD-ENDS — do not repeat" brief, the agent acts (injectable runner), a verify gate runs, and a falsifiable prediction↔outcome contract records a DECISION/fix on a win or a `FAILED_APPROACH` on a loss — so the next iteration's guard blocks it. Escalates the approach after consecutive losses, detects no-progress/context-rot via an iteration signature, and stops on converged / budget / max-iterations / no-progress. `onmc loop --goal "<text>" | --spec <file> [--max-iterations N] [--budget-tokens N] [--verify "<cmd>"] [--dry-run] [--json]`; `--dry-run` plans one iteration with zero spend. Agent + verify runners are injectable (default subprocess with timeouts). Deterministic, never-hang, no schema migration.

## [0.25.0] — 2026-06-23

### Added

- **`onmc pull --all` — federation from config.** Federates from every source in a new `federation.sources` list in `config.yaml` (each a bare path/url or `{path_or_url, label, ref}`), routing git URLs vs local paths to the existing federation engine. One source failing never aborts the rest; `--dry-run` previews, `--json` summarizes. A team's shared brains become one command to sync.
- **MCP `ask` tool** — exposes the NL-query-over-the-brain to connected agents: ranked, cited memories for a natural-language question, offline (no LLM synthesis in the tool path). Compact TOON-default / JSON; clean on empty brain.

## [0.24.0] — 2026-06-23

### Added

- **`onmc coverage --suggest` / `--apply`** — turns the knowledge-gap dashboard into an action list: for each top uncovered hotspot it proposes a memory title + kind (config→decision, hot file→invariant, else doc-fact) with a churn-based rationale, deterministically and with no LLM. `--apply` stubs those as low-confidence `coverage-stub` memories (idempotent by stable id), making the gap board a zero-friction to-do.
- **MCP `get_profile` tool** — exposes the evolving user profile (preferences / patterns / mistakes-to-avoid / tooling) so an agent connected over MCP starts a session already knowing the user. Compact TOON-default / JSON; graceful-empty when no user DB.

### Added

- **Obsidian knowledge-graph export.** `onmc wiki --format obsidian` writes provenance-rich memory notes, subsystem indexes, and relationship wikilinks to a private local vault by default.
- **Portable dashboard snapshots.** `onmc ui --export onmc-brain.html` writes one self-contained, zero-network HTML dashboard for demos, screenshots, and handoffs, with embedded data escaping and a restrictive Content Security Policy.

## [0.23.0] — 2026-06-23

### Added

- **`onmc profile` — an evolving user profile that sharpens across sessions.** Derives a behavioral profile from accumulated `~/.onmc` user-scope memories + feedback: recurring preferences, coding patterns, frequent mistakes/corrections, and tooling choices — weighted by confidence × feedback × recency decay (reuses the recall decay model). Deterministic, no LLM. `onmc profile show|rebuild [--json]` renders Preferences / Patterns / Mistakes-to-avoid / Tooling.
- The **SessionStart boot-digest** now injects a compact `👤 Your profile` block (top preferences + mistakes-to-avoid), terse by default, firewall-aware (emits an observability event; keeps the profile in context). Empty/missing user DB injects nothing and never raises.

## [0.22.0] — 2026-06-23

### Added

- **`onmc import` — adopt other tools' knowledge into the portable brain.** The flip-side of `onmc plug`: plug wires an agent to *use* onmc; import pulls another tool's existing knowledge *in*. `onmc import omc` ingests `.omc/skills/*.md` (project) and `~/.omc/skills/*.md` (user) as portable Skills tagged `imported:omc`; `onmc import hermes` ingests `MEMORY.md`/`USER.md` as MemoryEntry records tagged `imported:hermes`; `onmc import <path> [--as skill|memory]` is a generic markdown importer. Dedup by stable id → idempotent re-import; `--dry-run`, `--json`.

## [0.21.0] — 2026-06-23

### Added

- **`onmc savings` — a "Memory Wrapped" token-ROI card.** A shareable, screenshot-worthy terminal card proving onmc's value: headline context-token reduction %, memories/skills/playbooks inventory, repeated-failure drop, wasted-attempts saved, and top hotspots covered. Reuses the deterministic bench harness + coverage compiler; every simulation/estimate metric is honestly labelled. `--json` for machine output.
- The **statusline** now also carries a compact `N mem · M skills · ~X% ctx saved (sim)` memory-health segment.

## [0.20.0] — 2026-06-23

### Added

- **`onmc ask "<question>"`** — a natural-language query over the memory brain. Returns the most relevant memories with citations and, when a provider is configured, a concise synthesized answer grounded in those memories. Offline-safe: ranking + citations always work with zero network; the LLM synthesis pass is best-effort and never breaks the command. `--limit`, `--json`, `--no-synth`.
- **MCP `get_skills` tool** — agents connected over MCP can discover and fetch the repo's portable skills mid-task. Optional `query`/`tags` rank the most relevant skill first; compact TOON-default / JSON output.

## [0.19.0] — 2026-06-23

### Added

- **Context firewall — "the memory layer with zero context tax."** Operational notification noise (capture confirmations, staleness warnings, "surfaced N" meta-notices, danger-guard advisories) is now routed to a side sink instead of the agent's context window, so context carries only high-value recall. New `notify/` subsystem: `NotifyEvent` + sinks — FileSink (default, JSONL → `.onmc/notify.log`), DiscordSink, SlackSink (stdlib urllib, short timeout, exception-safe, no-op without a webhook). Routine events batch; failures emit immediately. Config precedence env > config.yaml > default. `onmc notify test|status|tail`.
- Hooks (per-prompt recall, boot-digest, pre-tool-use) emit observability events to the sink while keeping recalled memories/skills — and any real safety block — in context. Kill-switch `ONMC_FIREWALL=0` restores prior in-context behavior; every hook still exits 0 and never blocks.

## [0.18.0] — 2026-06-23

### Added

- **`onmc skill` — portable, self-improving skills.** The flagship answer to OMC-style Skills, but git-portable, cross-agent, and provenanced instead of siloed in one tool's dir. Promote a playbook (or auto-detect a recurring fail→fix pattern) into a named Skill that **auto-injects when relevant** (per-prompt recall + SessionStart hooks, terse, ranked by relevance × success-rate, never-block) and **gets better the more it's used** (`onmc skill feedback up|down` feeds `use_count`/`success_count`/`confidence`; unused skills decay out of injection). `onmc skill promote|list|show|feedback|prune`.
- Skills are **cross-agent portable** — `onmc sync` exports them to `.agent-memory/skills/` and the open **AGENT-MEMORY-SPEC** documents the shape, so the same skill works in Claude Code, Codex, and Cursor.
- Schema migration v7 (`skills` table).

## [0.17.0] — 2026-06-22

### Added

- **`onmc feedback <memory-id> up|down`** — a human/agent-in-the-loop trust signal. `up` reinforces a memory (raises `feedback_score` + `confidence`); `down` demotes it toward a 0.15 floor without zeroing it. Both touch `updated_at`, so the signal feeds the v0.16.0 confidence-decay ranking — positive feedback slows a memory's ageing, negative demotes it. `--note`, `--json`.
- **MCP `get_coverage` + `get_digest` tools** — agents connected over MCP can now query the knowledge-gap dashboard ("where are the blind spots?") and the knowledge changelog ("what did this repo learn since `<ref>`?") without shelling out to the CLI. Compact TOON-default / JSON output; bad refs error cleanly.

## [0.16.0] — 2026-06-22

### Added

- **`onmc coverage`** — a knowledge-gap dashboard. Joins the repo's file-churn index against memory `source_ref` associations to answer "where are the blind spots?". Headline output is **Top Uncovered Hotspots**: high-churn files with zero memory coverage, sorted by commit frequency — the landmines most likely to cause regressions. Plus per-subsystem coverage rows (worst-first) and an overall coverage %. `--json`.

### Changed

- **Confidence-decay recall ranking** — a memory's confidence contribution now decays exponentially with time since last corroboration (90-day half-life, 0.3 floor), so stale never-reconfirmed memories rank below fresh/corroborated ones of equal textual relevance. Positive feedback slows the ageing; textual overlap is never penalised. `decay_factor` is exposed on `ScoreBreakdown` and flows into the MCP `why` explanation.

## [0.15.0] — 2026-06-22

### Added

- **`onmc pull <git-url>`** — federate from a *remote* repo, not just a local path. Shallow-clones the repo to a temp dir, imports its committed `.agent-memory/` (federated + deduped), and cleans up the clone. Detects http(s)/ssh/scp git URLs vs local paths; `--ref <branch|tag>` to pull a non-default branch; repo label derived from the URL.
- **Recall explanations in MCP output** — each recall result returned over MCP now carries `provenance` (source citation) and a compact `why` score breakdown (final score + dominant components), in both the default TOON path and the JSON path. Additive and backward-compatible; gracefully omitted when absent. Agents consuming onmc over MCP can now see *why* a memory surfaced.

## [0.14.0] — 2026-06-22

### Added

- **`onmc pull <source>`** — cross-repo brain federation. Import another repo's committed `.agent-memory/` export into this repo's brain; imported memories are tagged `federated:<repo>` so they're recallable here yet clearly attributed and never confused with local knowledge. Dedups by stable id (idempotent re-pull), reuses the sync importer. `--label` / `--json`.
- **Source citations on recall** — every surfaced memory now carries a compact provenance tag (`source_type · ref · file`), terse-mode aware, gracefully omitting missing fields, so an agent can trust and trace what it recalls.

### Changed

- **Recall ranking quality** — normalized component-score blend (overlap *ratio* + scaled confidence + feedback) so precise queries beat noisy ones at equal raw overlap; deterministic tie-break on `(confidence, recency)` instead of alphabetical title; per-result score breakdown exposed for explainability.

## [0.13.0] — 2026-06-22

### Added

- **`onmc onboard`** — a guided new-developer tour built from the repo's own memory: repo overview → danger zones (top hotspots + the invariants that govern them) → key decisions/invariants → top playbooks → start-here files. Interactive paginated walk, or `--steps` for a non-interactive dump. The senior-who-read-every-commit, in five minutes.
- **`onmc digest --since <ref>`** — a knowledge changelog: what the repo *learned* since a git ref, grouped by kind (decisions / invariants / gotchas / failed approaches). Prefers a committed `.agent-memory/` diff (reuses the memory-diff engine); falls back to `created_at`-after-ref when no committed export exists. `--json` for machine output.

## [0.12.0] — 2026-06-16

### Added

- **`onmc doctor` install/wiring checks** — detects a stale or broken `onmc` on PATH shadowing the installed version, hooks pointing at an unresolvable binary ("hooks will silently fail"), and an unresolvable MCP command. Subprocess-probed with a timeout; warnings keep exit 0, errors only on real failures.
- **Zero-effort SessionEnd auto-capture** — the SessionEnd hook now also mines the just-ended session transcript into durable memory heuristically (decisions / fixes / invariants), capped and deduped, `source_type=session`. `ONMC_AUTOCAPTURE=0` to opt out; always exits 0, never blocks the session. Plus a manual `onmc capture`.

## [0.11.0] — 2026-06-16

### Added

- **`onmc recall "<error/stacktrace>"`** (also reads piped stdin) — "have we hit this before?" Normalizes line numbers / hex / UUIDs / timestamps so error variants match the same memory, then surfaces the prior fix (biased toward failed-approach / gotcha). Plus an MCP `recall` tool so an agent self-checks on errors.
- **`onmc blame <file>`** — git-blame for knowledge: maps a file's functions/classes/headings to the invariants, decisions, and incidents that govern them (heuristic symbol extraction + attachment), with file-level memories bucketed separately.

## [0.10.0] — 2026-06-16

### Added

- **`/onmc-why` / `/onmc-guard` / `/onmc-brief` / `/onmc-statusline`** — first-class Claude Code slash commands, shipped in the plugin and installed by `onmc plug claude-code`.
- **PreToolUse danger-guard** — before the agent edits a file, onmc injects file-level danger signals (high churn, invariants, recorded failed approaches) as non-blocking context. Never blocks the edit; silent on safe files.
- **`onmc check`** — flags staged/changed files that touch a recorded invariant or failed-approach dead-end (`--staged`/`--file`/`--base`, `--strict` to fail, `--install-hook` for an idempotent pre-commit hook).

## [0.9.0] — 2026-06-16

### Fixed

- **Claude Code plugin manifests now match the real spec** (`code.claude.com/docs`): `displayName`, an `author` object, `mcpServers`→`./.mcp.json` and `hooks`→`./hooks/hooks.json` path refs, and a marketplace entry with the required `name`/`owner`/`source` fields. Adds plugin-root `.mcp.json` and `hooks/hooks.json` so a one-step `/plugin marketplace add` + `/plugin install` actually works.

### Added

- **First-class Codex integration** — `AGENTS.md` stanza + a real `~/.codex/config.toml` MCP block (`codex mcp add onmc -- onmc serve --mcp`).
- **Terse injection mode** — `ONMC_TERSE=1` / `--terse` emit only high-signal tokens (compact `INVARIANT:` / `FAILED(don't retry):` / `FIX(worked):` lines, hard token budget, top-ranked only). Terse is the default for the per-prompt recall and boot-digest hooks (full output via `ONMC_VERBOSE=1`) — ~90% fewer characters of injected context.
- **Fast, never-blocking hooks** — the per-prompt and session-start hooks now run under a time budget (emit-ready-or-nothing, always exit 0), with lazy imports for fast startup, bounded + cached candidate retrieval, and graceful degradation to lexical. Any exception emits nothing and exits 0 — the host agent is never blocked or slowed.

## [0.8.0] — 2026-06-16

### Added

- **`onmc plug <claude-code|codex|cursor|omc|omx|all>`** — one command wires onmc into a target agent (Claude Code hooks + `.mcp.json`, a Codex `AGENTS.md` stanza, a Cursor rules file, copy-paste adapters for oh-my-claudecode / oh-my-codex). Idempotent; plus `docs/integrations/` guides. Other agents adopt onmc's memory (`onmc brief`, `onmc guard`) without changing their workflow.
- **`AGENT-MEMORY-SPEC.md`** — an open, versioned specification for the `.agent-memory/` format (directory layout, record schemas + enums, identity/provenance/staleness semantics, forward-compat, conformance), so any tool can read and write one shared brain.
- **`onmc spec print` / `onmc spec validate`** — make the spec executable: validate that a `.agent-memory/` directory conforms (pass/fail with specific errors).

## [0.7.0] — 2026-06-15

### Added

- **`onmc why --at <commit>`** — time-travel: recompute a file's why-report as of a past commit (git history bounded to the commit; memory entries are labeled as reflecting the current store).
- **`onmc memory-diff <commitA> <commitB>`** — diff the committed `.agent-memory/` export between two commits (added / removed / changed memories), with a file-name-diff fallback when no brain is committed.
- **`onmc wiki [--output DIR]`** — generate a browsable multi-page knowledge wiki (index, per-subsystem pages, relationship graph) from memory + the memory-edge graph.

### Changed

- `onmc claude-md generate` now produces clean, coherent output (sentence-boundary truncation, code fences reduced to breadcrumbs, deduped source labels).
- A memory-grounded PR bot posts `onmc why` / `onmc guard` context on pull requests; the brain-freshness check is now informational (no longer shows a failing status).

## [0.6.0] — 2026-06-15

### Added

- **`onmc guard`** — failure-aware loop: surfaces recorded `failed_approach` / `did_not_work` memory for a task as explicit "DO NOT retry these dead-ends" guidance, as a CLI command and a `guard_task` MCP tool, so an agent never repeats a recorded mistake.
- **`onmc statusline` / `onmc hud`** — memory-health observability: a compact one-line statusline (mem count, freshness %, stale count, tokens/day) for Claude Code's `statusLine`, and a richer HUD panel (counts by kind, freshness bar, coverage proxy, recent LLM cost aggregated from the call log).
- **`onmc bench`** — a deterministic, reproducible proof harness comparing an agent with vs without onmc memory (built-in scenario: repeated-failure rate 100% → 0%, context tokens −97%).
- **Local embeddings rerank** — opt-in hybrid retrieval layering semantic cosine similarity over FTS5, with a dependency-free deterministic default embedder (vectors cached in SQLite, migration v6); gated by `ONMC_EMBEDDINGS`.
- **Claude Code plugin + marketplace manifest** (`.claude-plugin/`), an enhanced **AGENTS.md**, and an AI-Ready badge.
- **Dogfooding**: the repo now ships its own committed `.agent-memory/` brain plus a brain-freshness CI check.

## [0.5.0] — 2026-06-15

### Added

- **`onmc consolidate` (memory "dreaming")** — a manual command plus a SessionEnd hook that self-improves the store between sessions: dedups near-duplicate memories, merges and promotes high-feedback ones, demotes/flags stale, and builds a memory-edge graph (migration v5: `supersedes` / `contradicts` / `relates` / `duplicate_of`) surfaced in `onmc why`. Manual memories are never deleted; `--dry-run` previews.
- **`onmc tui`** — a `rich`-based interactive brain browser (Memories / Playbooks / Tasks / Status) with inline confirm/reject.
- **`onmc playbook`** — memory-derived, provenance-tracked, git-portable reusable playbooks synthesized from high-signal memory (migration v4).
- **`onmc why`** — explains why a file looks the way it does from memory + git history (deterministic core, optional LLM narrative).
- **Per-prompt surgical recall** — a UserPromptSubmit hook injecting only the memory relevant to the current prompt.
- **Dual-scope user memory** — a `~/.onmc/user.db` layer (`onmc user`) of durable preferences that travels across all repos and leads the SessionStart boot digest.
- **FTS5 hybrid memory search** and **provenance staleness** (`onmc memory verify` / `prune`, migration v3).
- **SessionStart boot digest** injecting a compact repo-memory digest at session start.

### Changed

- **MCP output is now TOON by default** (~50% fewer tokens than JSON for record lists); JSON via `ONMC_MCP_FORMAT=json` or `?format=json`. SQLite and `.agent-memory/` export stay JSON.
- **Tag-driven release pipeline**: pushing `vX.Y.Z` runs the gate, builds, and creates a GitHub Release; the PyPI publish job is gated behind `vars.PYPI_TRUSTED_PUBLISHING` and skips (does not fail the run) until trusted publishing is configured. See `docs/RELEASING.md`.

## [0.4.0] — 2026-06-15

### Fixed

- **Claude Code hooks now target the real hook API.** The previous integration registered a `PostCompact` event that does not exist in Claude Code, wrote the continuation brief to a file nothing reads, and installed hooks globally so they fired in every repo. Hooks are now project-scoped (`.claude/settings.json`): `PreCompact` plus `SessionStart` with matcher `"compact"`, with context injected through the documented `hookSpecificOutput.additionalContext` stdout contract. Hook commands read the JSON payload Claude Code passes on stdin, and `pre-compact` enriches the compaction snapshot from the live session transcript — no manual task journaling required. Uninstall is surgical and also cleans up legacy global installs.
- **MCP registration moved to `.mcp.json`.** Claude Code never read `mcpServers` from `settings.json`; registration was silently ignored.
- **`onmc mine` now finds real transcripts.** Discovery previously used a fabricated `sha256`-hashed `sessions/` layout; it now targets the actual `~/.claude/projects/<sanitized-path>/<session-uuid>.jsonl` layout and parses the real message schema (text and `tool_use` content blocks, sidechain transcripts skipped).
- **Re-ingest no longer destroys feedback.** `onmc memory confirm`/`reject` scores (and original creation times) survive every `onmc ingest`.
- **Storage hygiene.** Connections are now closed (previously leaked in the MCP server and watch mode), WAL and a busy timeout are enabled, and schema migrations are versioned.
- **`onmc init` now gitignores `.onmc/`.** The docs always claimed the local state dir was gitignored, but nothing enforced it — a `git add -A` would commit the binary SQLite store and the LLM call log (which can contain repo source). Init now adds an idempotent `.onmc/` entry to the repo's `.gitignore`. Only the JSON export under `.agent-memory/` is meant to travel with the repo.
- **MCP startup banner** told users to register the server in `settings.json`, which Claude Code ignores; it now shows `claude mcp add` and the project `.mcp.json` form.
- OpenAI requests send `max_completion_tokens` (required by newer models) with a one-shot fallback to `max_tokens` for older ones.

### Added

- **MCP tools.** `onmc serve --mcp` now exposes `search_memory`, `get_brief`, `record_attempt`, `record_memory`, and `list_tasks` alongside the existing read-only resources, plus a `--repo` flag so the server no longer depends on its working directory.
- **LLM call retries.** Provider calls retry up to 3 attempts with exponential backoff and jitter on 429/5xx/timeouts, honoring `Retry-After`.
- **End-to-end test suite** (`tests/test_e2e.py`) drives the real `onmc` binary as a subprocess through the full memory lifecycle, the Claude Code hook stdin/stdout contracts, transcript-mining discovery, a `sync`→clone→`restore` roundtrip, and a real MCP stdio client/server handshake.
- **FTS5 full-text search** on memory artifacts for fast keyword queries across stored knowledge.
- **Staleness detection** marks memory entries as stale when the files they reference have changed since ingest.
- **Boot digest** (`onmc hooks session-start`) compiles a compact ≤400-token repo brain summary injected at every Claude Code session start.

### Changed

- `onmc hooks post-compact` is replaced by `onmc hooks session-start` (a deprecated alias remains).
- `.onmc/logs/llm-calls.jsonl` now stores truncated prompts/responses by default (full payloads with `ONMC_LOG_FULL_PROMPTS=1`) and rotates at 10 MB.

## [0.3.0] — 2026-03-31

### Added

- **God Mode setup wizard** (`onmc setup`): a guided onboarding flow that detects repo shape, optionally configures an LLM provider, runs ingest, generates `CLAUDE.md`, and offers Claude Code hook/MCP/post-commit integration in one command.
- **LLM-powered ingest upgrade**: `onmc ingest` now optionally mines commit batches and docs for decisions, invariants, failed approaches, design conflicts, and gotchas, with Pydantic validation and logged provider calls.
- **`CLAUDE.md` generation and maintenance** (`onmc claude-md`): generate, preview, update, and watch a repo-specific `CLAUDE.md` synthesized from stored memory and active tasks.
- **Claude Code transcript mining** (`onmc mine`): read Claude Code assistant transcripts, exclude user turns, extract attempts and durable memory, and link findings back to tasks when possible.
- **LLM-ranked briefs**: `onmc brief` can now rerank candidate memory with task-specific relevance reasons while preserving the deterministic fallback.
- **Upgraded `teach` mode**: richer teaching output plus interactive follow-up Q&A with the same memory spine.
- **Health checks** (`onmc doctor`): audit repo state, memory freshness, provider readiness, Claude integration, and sync state from one command.
- **LLM call logging**: all provider calls are appended to `.onmc/logs/llm-calls.jsonl` with timestamps, token counts, model, and latency.

### Changed

- README and architecture docs now describe the God Mode workflow, `CLAUDE.md`, transcript mining, doctor, and optional LLM-assisted ingest/ranking.
- `teach` output now supports a richer schema while remaining backward-compatible with the earlier prompt contract.

### Fixed

- `solve` / `review` / `teach` now remain strict about provider configuration unless `--no-llm` is explicitly requested.
- Transcript-to-task linking now uses tokenized file overlap instead of exact string matching.

## [0.2.0] — 2026-03-31

### Added

- **Git-portable memory sync** (`onmc sync`): export the full memory store to `.agent-memory/` as committable JSON, restore it on any machine or cloud environment with `onmc sync --restore`, and auto-export on every commit with `onmc sync --install-hook`.
- **Claude Code compaction hooks** (`onmc hooks`): install PreCompact and PostCompact hooks that snapshot active task context before compaction and inject a continuation brief after, so Claude Code resumes without losing engineering context.
- **CompactionSnapshot model**: new first-class record type that stores active files, recent decisions, working hypothesis, last error trace, and next step at each compaction boundary.
- **Continuation brief compiler**: a purpose-built brief that answers "where were we, what did we decide, what were we trying, what's next" — distinct from the standard `onmc brief` task compiler.
- **Read-only MCP server** (`onmc serve --mcp`): exposes the full memory store as MCP resources so any MCP-compatible agent can query repo context mid-session. Resources: `onmc://brief`, `onmc://memory/*`, `onmc://tasks`, `onmc://task/{id}`, `onmc://snapshot/latest`, `onmc://status`.
- **Incremental ingest** (`onmc ingest --files`): re-ingest specific files without a full repo scan. Git hook mode via `onmc ingest --install-hook` auto-ingests changed files on every commit.
- **Public Python API** (`import onmc`): all CLI capabilities exposed as a typed importable library. `onmc.init()` returns an `OnmcRepo` with `.memory`, `.task`, `.hooks`, `.sync`, `.brief()`, and `.ingest()` surfaces. `py.typed` marker added for mypy support.

### Changed

- Quickstart updated to distinguish fresh-repo flow from clone-and-restore flow.
- README reorganized with agent integration reference table and MCP setup instructions.

### Fixed

- `.env` excluded from git tracking.

## [0.1.0] — 2026-03-24

Initial release.

- `onmc init`, `onmc ingest`, `onmc brief`
- Task and attempt lifecycle tracking
- Memory artifact recording and inspection
- Optional LLM modes: `onmc solve`, `onmc review`, `onmc teach`
- Anthropic and OpenAI provider support
- Full test suite, CI, and PyPI publishing scaffold
