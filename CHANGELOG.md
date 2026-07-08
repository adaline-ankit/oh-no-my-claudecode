# Changelog

All notable changes to this project are documented here.

## [Unreleased]

## [0.99.0] — 2026-07-08

### Added

Agent-experience commands — planned with `onmc mission`, built as self-registering subpackages (zero `cli.py` edits):

- **`onmc doctor`** — one-command integration health check that diagnoses whether onmc is wired into Claude Code: onmc initialized, version, on PATH, hooks installed, MCP registered, `/onmc` wrap command present + active — each with an actionable fix. Folds in the existing repo/memory/provider/sync health report as a superset. `--json` envelope (`integration` + `repo_health` + `summary`); exit 1 on any failure. Directly addresses the onboarding confusion where a stale/uninitialized setup gave no way to self-diagnose. (#323)
- **`onmc explain [receipt]`** — plain-English verdict of a run receipt (latest by default, or by path/short-hash). Explains *why* a run did or did not verify, with a dedicated explanation for every stop reason — including the `no-changes` vacuous pass (verify passed but the agent changed nothing, e.g. blocked edits), so a false-green is legible at a glance. `--json`. (#321)
- **`onmc context <file>`** — one-shot context for a file: codegraph blast radius (dependents / imports / tests) plus relevant memory entries, reusing the existing codegraph and memory APIs. `--json`, `--limit`. A better codegraph integration for agents about to edit a file. (#322)

## [0.98.0] — 2026-07-08

### Fixed

Three bugs surfaced by dogfooding the `/onmc` deep-wrap switch in a real Claude Code session:

- **`onmc autopilot` no longer reports false-green** (P0): a run could print `VERIFIED / converged` and spend real cost while writing zero code — an agent whose edits were blocked (e.g. pending permission approval) produced no diff, yet a lenient verifier (`pytest` exiting 0 on pre-existing tests) was counted as a win, poisoning memory with fake success. The loop engine now gates a win on the agent actually changing the working tree: a new injectable `ChangeProbe` (default `git status --porcelain`, which also catches untracked new files a plain `git diff` would miss) is sampled before/after each agent step; a verify pass with an unchanged tree is recorded as a loss (`[no-op]`) and shows `NOT VERIFIED — no-changes`. A new `no_change_limit` breaker (default 2) stops the loop after consecutive no-ops. (#318)
- **`onmc ui` auto-falls-back to the next free port** when the requested one is busy, instead of crashing with `Address already in use` — which previously left users viewing a stale dashboard (rooted in another repo) where their runs showed as "No runs yet". `port=0` still lets the OS choose. (#319)
- **`onmc --version` / `-V`** now prints the installed version (previously errored `No such option: --version`); the installer's day-1 banner is aligned with the `onmc quickstart` card. (#317)

## [0.97.0] — 2026-07-08

### Fixed

- **`curl | bash` onboarding now works non-interactively** (surfaced by real-world testing): the installer force-upgrades an existing install (`uv tool install --force` / `pipx install --force` / `pip install --user --upgrade`) instead of no-op'ing on a stale version; the integration step runs with stdin from `/dev/null` and falls back to `onmc setup --yes` so it can't consume the piped script or loop on a prompt. `onmc setup` now auto-uses defaults (never prompts/loops) under `--yes` or when stdin is not a TTY. (#315)

## [0.96.0] — 2026-07-06

### Added

Frictionless onboarding — get from zero to integrated in one line, oh-my-zsh style:

- **One-line installer** — `curl -fsSL https://raw.githubusercontent.com/adaline-ankit/oh-no-my-claudecode/main/install.sh | bash` detects uv/pipx/pip, installs onmc, runs `onmc quickstart`, prints a day-1 banner. README updated with the one-liner up top. (#311)
- **`onmc quickstart`** — one idempotent, zero-config command that composes memory init + `plug claude-code` (hooks + MCP + `/onmc` slash command) + `wrap --default-active`, then prints a "you're ready" card with the day-1 commands. (#312)
- **Tiered help** — `onmc --help` no longer dumps 136 commands: the root help surfaces ~8 **Core** commands and points to `onmc commands`, which groups everything into Core / Orchestrate / Memory / Trust / Fun / Integrations / Other (`--all`, `--category`, `--json`). (#313)

## [0.95.0] — 2026-07-06

### Added

- **`onmc ui --serve`** — shared dashboard: bind beyond localhost with optional bearer-token auth (`--token` / `ONMC_UI_TOKEN`) and a `POST /api/live/ingest` endpoint so a remote onmc can push telemetry events to one central dashboard. Default localhost/no-auth behavior unchanged. (#308)
- **`onmc wrap --managed`** — org hard-lock: install the onmc hooks into Claude Code's managed-settings path (per-OS default + `--managed-path` override) so users cannot disable the wrap — making `/onmc` mandatory org-wide. Merge preserves other managed keys; `onmc unwrap --managed` removes only onmc's; graceful (prints manual JSON) when the path isn't writable. `onmc wrap status` reports managed enforcement. (#309)

### Fixed

- **`onmc land`** — fetch unresolved review threads via `gh api graphql` instead of the invalid `gh pr view --json reviewThreads` field (the 2nd bug dogfooding the lander surfaced); `land status`/`run` now query PR state without erroring. (#307)

## [0.94.0] — 2026-07-06

### Added

- **`/onmc` session switch + deep-wrap control plane** — onmc becomes a toggleable control plane over Claude Code. `onmc wrap` installs the hooks plus a `/onmc` Claude Code slash command (`.claude/commands/onmc.md`, body runs `onmc wrap toggle`); `onmc wrap on|off|toggle|status` control it, and `--default-active` auto-engages on every SessionStart. When **active**, onmc owns the full Claude Code lifecycle: SessionStart memory-grounding, per-prompt recall + dead-ends + route/guard, PreToolUse gate + native-Task→`onmc swarm` redirect, PostToolUse/SubagentStop live telemetry, Stop receipt, PreCompact flush. When **off**, every hook no-ops (exit 0) — Claude Code runs stock. Type `/onmc` mid-session to flip it, exactly like `/caveman`. (#305)

## [0.93.0] — 2026-07-06

### Added

Dogfood-infra wave — the tooling onmc uses to ship onmc, built + landed by an onmc swarm:

- **`onmc refinery`** — Bors-style serialized merge queue (rebase → wait green → merge → pop; kicks failures back), gating quality AND CodeQL. The principled fix for merge-race starvation. (#297)
- **`onmc land <pr>`** — first-class safe PR lander: poll → rebase-if-behind → resolve threads → squash-merge with admin, contention-aware. Pure planner + injectable gh driver. (#299, fix #302)
- **`onmc preflight --exact` / `--fix`** — mirrors the CI quality gate exactly (pinned ruff/typer) and auto-heals ruff + stale cli-reference before push, so agents self-heal instead of round-tripping CI. (#300)
- **Live agent telemetry** — a `.onmc/live/events.jsonl` event bus (`telemetry` module), a PostToolUse/SubagentStop Claude Code hook that captures agent activity, `onmc live` / `onmc live tail`, and swarm state-transition emit. (#301)
- **`onmc ui` Agents view + live feed** — see every swarm/unit/receipt and a live-updating activity feed (UI polls a new `/api/live` endpoint that tails the telemetry bus), plus orchestration actions (abort / land / mission). (#298, #303)

### Fixed

- **`onmc land`** — derive `merged` from PR `state` (the `gh pr view --json merged` field doesn't exist); surfaced by dogfooding the lander on a real PR. (#302)

## [0.92.0] — 2026-07-06

### Added

Agent-ecosystem interop — onmc as the accountability/memory layer over other agent runtimes. All three are optional, import-guarded extras with graceful fallback; built in parallel by an onmc swarm, each its own PR:

- **Optional LangChain document-loader importer (`[langchain]`)** — `run_import(storage, "langchain", loader=…)` ingests any LangChain-compatible source (PDFs, web, notebooks, directories) into onmc memory candidates via LangChain loaders + splitters. Absent extra → reports unavailable; existing importers unchanged. (#293)
- **`onmc crews` — optional CrewAI interop (`[crewai]`)** — `crews export` converts an onmc mission/swarm plan into a portable CrewAI crew spec (pure, always works); `crews run` executes a crew under an onmc accountability receipt via an injectable runner (requires the extra; exits cleanly if absent). (#295)
- **`onmc teams` — optional AutoGen interop (`[autogen]`)** — the same pattern for Microsoft AutoGen / AG2 teams: `teams export` (pure) + `teams run` under an onmc receipt. (#294)

All offline-tested (import-guarded, injected fake runners/loaders — no network, no real LLM calls).

## [0.91.0] — 2026-07-06

### Added

The **agent-observability track, batch 8** — perf + sharing. Dogfood-swarm built, each its own PR:

- **`onmc bottleneck [--top N]`** — surfaces the slowest goals and models plus outlier runs (wall/iterations > p90 or 2× median) with a "time sinks" summary, from run receipts. `--json`. (#289)
- **`onmc share [--scorecard] [--private] [--dry-run]`** — publishes a dashboard HTML snapshot (or the scorecard markdown) to a GitHub Gist and returns the public URL: a one-command shareable link for demos. `--dry-run`/`--json` never touch `gh`. (#291)

## [0.90.0] — 2026-07-06

### Added

- **`onmc daily` — don't-break-the-chain calendar streak** — a calendar-DAY engagement streak (GitHub-contribution / Duolingo style), a distinct axis from `coach`'s per-event combo. `onmc daily` shows current chain, longest chain, total active days, and days-to-next-milestone (7/30/100); `daily grid` renders a contribution-style calendar; `daily checkin` marks a day active. Active days are the union of explicit check-ins and verified run receipts; a grace rule extends the streak from yesterday until today's first check-in. Pure stdlib, deterministic (injected `today`), auto-discovered. Completes the fun track. (#268)

## [0.89.0] — 2026-07-06

### Added

The **agent-observability track, batch 7** — prediction + comparison. Dogfood-swarm built, each its own PR:

- **`onmc estimate <goal> [--model M]`** — predictive PRE-run forecast: clusters historical receipts by goal-keyword overlap and projects expected cost (median + range), wall time, iterations, and probability-of-verified; honest fallback to overall averages / "no history" under 3 similar runs. `--json`. (#287)
- **`onmc compare <swarm-a> [swarm-b]`** — side-by-side comparison of two swarm runs (units, verified rate, wall, cost, avg iterations, models) with per-metric winners + a one-line verdict; defaults the second arg to the most recent other swarm. `--json`. (#286)

## [0.88.0] — 2026-07-06

### Added

The **agent-observability track, batch 6** — spend + distribution. Dogfood-swarm built, each its own PR:

- **`onmc cost [--days N]`** — spend breakdown + forecast from run receipts: total, by-model, by-day, cost-per-verified-run, and a labelled linear monthly projection. Honest about unknown/zero cost. `--json`. (#283)
- **`onmc prbadge <pr> [--dry-run]`** — posts a shareable "verified-work" badge comment on a GitHub PR from local receipts (honest zero-state, never a fabricated %); `--dry-run`/`--json` never call `gh`. Turns every onmc-built PR into proof-of-work. (#284)

## [0.87.0] — 2026-07-06

### Added

- **`onmc blackboard post|show <swarm-id>`** — an append-only shared-memory coordination board for swarms (`.onmc/swarm/<id>/blackboard.jsonl`): units post findings/claims/warnings/questions that other units and humans can read, instead of working blind. Pure stdlib core (`BoardEntry`/`append_entry`/`read_board`/`render_board`), clock-free; `--json`, `--kind`, `--unit` filters; defaults to the most recent swarm. The foundation for collaborative multi-agent runs. (#281)

## [0.86.0] — 2026-07-06

### Added

- **`onmc swarm plan --auto-model`** — self-improving model routing that closes the loop: `flywheel` learns which model wins per goal → `autoroute` picks it → `swarm plan` records it. When the flag is set, each planned unit is annotated with optional `suggested_model` / `suggested_model_confidence` fields (from `autoroute.suggest_model` over the flywheel report) and a routing summary is printed. Fully backward-compatible — absent the flag, planning is unchanged. Pure helper `swarm/auto_model.py`. (#279)

## [0.85.0] — 2026-07-06

### Added

The **agent-observability track, batch 5** — terminal-native "watch my agents". Planned via `onmc mission`, built by a dogfood swarm (each its own PR):

- **`onmc standup [--since 24h]`** — periodic daily-standup digest of agent RUN activity (runs, verified/failed + rate, cost, wall, per-model breakdown, top goals, notable failures) from run receipts. `--json`; honest empty-state. Distinct from `digest`/`timeline` (which cover memory). (#276)
- **`onmc watch [--interval N]`** — auto-refreshing terminal live monitor of active swarms (the terminal-native complement to `onmc ui`; distinct from the one-shot `onmc missioncontrol`). Pure frame builder reusing the missioncontrol readers; `--once` renders a single frame, `--json`, `--all`. (#277)

## [0.84.0] — 2026-07-06

### Added

The **agent-observability + fun track, batch 4** — SOTA "watch your agents" features. Planned via `onmc mission`, built by a dogfood swarm (each its own PR, fresh-clone isolation):

- **`onmc postmortem <swarm-id>`** — LLM-free, deterministic narrative recap of a completed swarm run (overview, per-unit lines, honest went-well / needs-attention summary), reusing the missioncontrol readers. `--json`; defaults to the most recent swarm. (#263)
- **`onmc race <goal>` / `--all`** — offline model/strategy tournament over run receipts: clusters by goal keywords, builds a per-model leaderboard (verified-rate then cost), declares a winner (≥3 verified runs, else honest "insufficient data"). `--json`; never fabricates cost. (#264)
- **`onmc swarmreplay <swarm-id>`** — time-travel step-by-step reconstruction of a swarm run's ordered timeline from manifest + receipts (units by `started_at`, one step per iteration). `--json` (stable UI-scrubber schema), `--step N`. (#265)
- **`onmc heatmap`** — GitHub-contributions-style calendar heatmap of agent run density from receipts, with month labels, legend, totals (runs, active days, busiest day, streak). `--weeks N`, `--json`. (#267)
- **`onmc formats` / `--schema`** — emits a versioned, introspection-derived spec of onmc's portable schemas (receipt, attestation, memory + manifest) for external-tool interop. `--json`. (#269)
- **`onmc achievements`** — gamified XP, verified-run streaks, milestones and badges computed purely from run receipts. `--json`; honest zero-state. (#270)

## [0.83.0] — 2026-07-06

### Added

The **fun track, batch 3** — stakes, personality, and reactions. Swarm-built (planned by `onmc mission`), each its own PR:

- **`onmc bounty` — task wagers** — put a points wager on a task (scaled by difficulty: easy 1× / med 2× / hard 3×), then `claim` the payout on completion or `forfeit` it. `bounty post`/`list`/`board`/`claim`/`forfeit`/`balance`, backed by a payout ledger. A stakes layer over your work. (#262)
- **`onmc persona` — personality presets** — pick a voice the fun layer speaks in: drill-sergeant, hype-beast, zen-master, pirate, or professional. `persona list`/`set`/`show`/`say`, deterministic per-event lines, persisted per-repo. (#261)
- **`onmc soundboard` — terminal event reactions** — map session events to fun inline reactions (🎉 test pass, 💥 build break, 🚀 merged) with custom `bind`/`unbind` and an optional terminal `--bell`. 20 built-in defaults; distinct from `notify` (external delivery). (#260)

All three are pure-stdlib, offline, deterministic, auto-discovered modules (zero hub edits).

## [0.82.0] — 2026-07-06

### Added

The **fun track, batch 2** — the delight features start composing each other. Swarm-built (planned by `onmc mission`), each its own PR:

- **`onmc leash` — guardrails-as-game** — define playful session "house rules" (soft advisory or hard buzz-triggering), check any action/text against them via deterministic offline pattern-matching (regex-first, literal fallback on bad patterns), and track compliance with a letter grade + clean-streak. `leash add`/`list`/`remove`/`check`/`score`. Distinct from `drift` (memory-directive enforcement on code) and `wrap` (hook tool-intercept). (#257)
- **`onmc vibe` — ambient agent-mood HUD** — a read-only dashboard that aggregates your `coach` streak, `whip` reward tally, and `quest` level into a single glanceable mood (🔥 on fire / 😎 cruising / 😐 meh / 🥵 struggling) with component readouts. Degrades gracefully when a source is absent. `onmc vibe` / `vibe mood`. (#256)
- **`onmc highlight` — session highlight reel** — mines verified receipts for the best moments (biggest win, gnarliest bug slain, longest streak, most efficient, fastest merge) into a curated, ranked, shareable recap (`--markdown`). Distinct from `replay` (step-by-step) and `timeline` (chronological). (#258)

All three are pure-stdlib, offline, deterministic, auto-discovered modules (zero hub edits).

## [0.81.0] — 2026-07-06

### Added

The **fun track** — features that make coding with an agent genuinely delightful. Built in parallel by an onmc swarm (planned by `onmc mission`), each its own PR:

- **`onmc whip` — the reins** — a live control surface over a running agent: `whip nudge`/`whip redirect` queue steering directives (persisted, priority-ordered) for the hooks layer to inject, while `whip treat`/`whip crack` record a reward/correction ledger that flywheel can learn from. `whip pending`/`clear`/`tally`. Steer the agent, whip it back on task, reward it when it nails something. (#247)
- **`onmc arena` — model gladiator** — record head-to-head model/approach bouts and maintain ELO ratings + a leaderboard: `arena bout A B --winner`, `arena leaderboard`, `arena standings`. Ratings recompute from an append-only bout log (can't drift). Turns model choice into a spectator sport backed by real numbers. (#248)
- **`onmc quest` — gamified RPG backlog** — your work as an RPG: XP from verified receipts, levels on a triangular curve, achievements, boss-fights (gnarly tasks), and loot (merged/completed). `quest log`/`achievements`/`stats`. Deterministic, receipt-driven. (#249)
- **`onmc coach` — live hype/roast commentator** — reacts to session events (test_pass, build_break, pr_merged, …) with deterministic hype/roast/dry quips and tracks current streak, best streak, and a combo meter. `coach react`/`streak`/`cheer`. The personality layer for long sessions. (#250)

All four are pure-stdlib, offline, deterministic, auto-discovered modules (zero hub edits).

## [0.80.0] — 2026-07-05

### Added

Third batch of memory features inspired by NousResearch's hermes-agent, built in parallel by an onmc swarm (planned by `onmc mission`), each its own PR:

- **`onmc skillguard` — skill write-approval gate with unified diffs** — the skill sibling of `memstage`: stages proposed skill create/edit/delete ops under `.onmc/skillguard/` for human review (unified diff via `difflib`) before anything touches the skill store. `stage`/`list`/`diff`/`approve`/`reject` with an audit trail; approve applies via the real skill path. Pure stdlib, deterministic ids. (#243)
- **`onmc selfimprove` — after-turn learning review** — scans a transcript/session for durable learnings (user corrections, repeated preferences, confirmed conventions) via pure regex heuristics and, with `--stage`, proposes them into the `memstage` approval queue for human sign-off. No LLM, no new deps; distinct from `flywheel` (which analyzes run receipts). (#242)

## [0.79.0] — 2026-07-05

### Added

Second batch of memory features inspired by NousResearch's hermes-agent, built in parallel by an onmc swarm (planned by `onmc mission`), each its own PR:

- **`onmc membudget` — memory-budget guard + consolidation suggester** — reports total store size with a per-kind breakdown, flags when over a configurable budget, and suggests concrete consolidation actions (DROP_STALE / MERGE_DUPLICATES / MOVE_TO_TOPIC). Read-only/advisory, deterministic, zero deps. (#231)
- **`onmc memprovider` — external memory-provider adapter interface** — a `MemoryProvider` Protocol + registry with a zero-dep `builtin` adapter over onmc's store plus import-guarded optional **Mem0** and **Supermemory** adapters (extras), running alongside built-in memory, never replacing it. `memprovider list`/`search`. (#232)
- **`onmc proxy` — OpenAI-compatible local proxy** — exposes onmc's configured LLM provider at `POST /v1/chat/completions` + `GET /v1/models` (stdlib `http.server`, no new dep) so external tools (Codex/Aider/Cline/Continue) can point at onmc. Pure request/response mappers are socket-free testable; graceful error JSON when no provider is configured. (#233)

## [0.78.0] — 2026-07-05

### Added

Three memory features inspired by NousResearch's hermes-agent, built in parallel by an onmc swarm (planned by `onmc mission`), each its own PR:

- **`onmc memguard` — memory-integrity firewall** — scans memory entries for adversarial content before they're trusted: prompt-injection phrasing, credential-exfiltration, SSH/backdoor patterns, and invisible/dangerous Unicode (zero-width, bidi overrides, tag chars). `memguard scan [--json] [--fail-on SEVERITY]` reports per-entry findings with severity + rule id. Pure stdlib, zero false positives on benign text — onmc's memory-poisoning defense, on the audit/attest trust moat. (#228)
- **`onmc session-search` — FTS5 full-text search over history** — fast keyword search across onmc's entire persisted store (memories, attempts, tasks, artifacts) via SQLite FTS5 with BM25 ranking + snippets, opening the DB read-only (never mutates schema); graceful `LIKE` fallback when FTS5 is absent. Complements `recall` (curated-memory KNN) with raw retrieval over everything. (#226)
- **`onmc memstage` — write-approval staging queue** — gates memory writes behind human review: `memstage add` stages a proposal (does NOT write the store), `list`/`diff`/`approve`/`reject` review it; approve persists via the real record path, reject keeps an audit trail. Portable `.onmc/memstage/`, deterministic ids. Onmc's accountability-layer thesis applied to memory. (#227)

## [0.77.0] — 2026-07-05

### Added

- **`onmc timeline` — repo-evolution narrative from the brain** — orders recorded memories (decisions, invariants, gotchas, dead-ends) by timestamp into a readable evolution story, grouped into periods (day/week) with one-line milestones. Great for onboarding and a shareable "how this repo got here". `--since`, `--group`, `--json`, `--markdown`. Pure/offline, clock-free core (the command layer injects `now`); undated memories are bucketed and noted, never given a fabricated timestamp.

Built via the `onmc mission`→swarm dogfood loop, its own verified PR (#224) — onmc building onmc.

## [0.76.0] — 2026-07-05

### Added

- **`onmc drift` — institutional-memory enforcement** — flags where the current code likely *violates* a recorded decision / invariant / convention (memory that guards, not just stores). Extracts a checkable directive from each memory (`never use X` → forbid, `always use Y` / `adopt Z` → require, `prefer A over B` → forbid B) and scans the codebase for contradicting evidence, reporting candidates with honest confidence (forbidden-token-present = strong; required-token-absent = weak) — explicitly for human review, never a proof. `drift check`, `--json`, `--min-confidence`. Pure/offline, reuses orggraph + memory; completes the institutional-memory arc: `orggraph` stores → `drift` guards.

Built via the `onmc mission`→swarm dogfood loop, its own verified PR (#221) — onmc building onmc.

## [0.75.0] — 2026-07-05

### Fixed

- **Release verifier now checks out the repository before `setup-python` caching** — closes the post-publish failure where PyPI upload succeeded but the final exact-version install verifier failed before it could run. This release proves the full hardened pipeline end to end.

### Changed

- **Re-issues the scorecard + handoff release on a fully green release workflow** — keeps the v0.74.0 user-facing feature set while making the final GitHub Actions release run auditable and green.

## [0.74.0] — 2026-07-05

### Added

- **`onmc scorecard` — shareable agent-readiness + trust report** — one command that aggregates the whole suite into a single viral artifact: repo agent-readiness (roast), top-agent trust (registry ledger), best verified model (flywheel), and institutional-memory coverage (orggraph entity/edge counts). Each signal degrades gracefully to `n/a` with an honest note; never fabricates numbers. `--json` and `--markdown` (emits a shields badge block). The capstone that ties onmc's suite together.
- **`onmc handoff` — portable task-context resume bundle** — packages everything a fresh agent or session needs to resume a task into one JSON bundle: goal + context pack + goal-ranked orggraph decisions + recorded dead-ends + recent run receipts. `handoff create <goal>` writes it; `handoff resume <file>` renders a briefing (dead-ends to avoid, decisions to respect, context, recent outcomes). Cross-session / cross-agent continuity. Each source degrades gracefully.

Both built via the `onmc mission`→swarm dogfood loop, each its own verified PR (#215, #216) — onmc building onmc.

## [0.73.0] — 2026-07-05

### Fixed

- **PyPI trusted publishing is now enabled and verified** — v0.72.0 was published
  to PyPI via OIDC after enabling the `PYPI_TRUSTED_PUBLISHING=true` repository
  variable, closing the gap where GitHub releases were green but PyPI stayed on
  an old version.

### Changed

- **Release pipeline now fails loudly instead of silently skipping PyPI** — release
  runs now verify the `vX.Y.Z` tag matches `pyproject.toml`, require PyPI trusted
  publishing readiness before upload, and install the exact published version from
  PyPI after upload to prove users can install it.
- **GitHub triage automation is productionized** — PR/issue automation now manages
  `priority/*`, `kind/*`, `size/*`, and `risk/*` labels, fixes the noisy generic
  docs label behavior, and grants the triage workflow the write permission needed
  to label PRs.

## [0.72.0] — 2026-07-04

### Added

- **`onmc autoroute` — apply flywheel's best-model recommendations per goal** — closes the self-improvement loop: `flywheel` *learns* which model wins for which kind of goal (from verified receipts), and `autoroute suggest <goal>` *applies* it — returning the recommended model, rationale, confidence, and basis (goal-keyword match → overall best → default fallback on insufficient data). Honest: confidence 0 and an explicit "insufficient data" basis when there isn't enough verified history. Pure/offline, reuses `flywheel`, `--json`. Now a swarm/loop can auto-select the historically-best model instead of a fixed default.

Built via the `onmc mission`→swarm dogfood loop, its own verified PR (#213) — onmc building onmc.

## [0.71.0] — 2026-07-04

### Added

- **`onmc registry` — agent reputation trust ledger** — aggregates signed `attest` attestations into a queryable, rankable per-agent trust ledger: only signature- *and* claim-verified attestations count toward reputation (tampered/wrong-secret ones are flagged `invalid`, never counted); computes verified-rate, distinct goals, first/last seen, and a deterministic `trust_score`, then ranks agents on a leaderboard. `registry add <attestation>`, `registry rank`, `registry agent <subject>`, `--json`. The marketplace/reputation layer on top of `attest` — completing the agent-economy trust stack (badge → flywheel → attest → registry).

Built via the `onmc mission`→swarm dogfood loop, its own verified PR (#211) — onmc building onmc.

## [0.70.0] — 2026-07-04

### Added

- **`onmc crossrepo` — cross-repo impact map + federated recall** — the multi-repo super-agent frontier: given N sibling repo paths, `crossrepo scan` builds the ripple surface (top-level modules shared across repos, so a change in repo A that would ripple into repo B is visible), and `crossrepo recall <query>` runs a unified federated memory search across the repos' `.agent-memory/` exports, attributing every hit to its source repo. Pure/deterministic/offline, reuses the federation exporter schema, `--json`. Multi-repo understanding is explicitly unsolved at the agent layer — this is onmc's wedge.

Built via the `onmc mission`→swarm dogfood loop, its own verified PR (#209) — onmc building onmc.

## [0.69.0] — 2026-07-04

### Added

- **Optional osv-scanner dependency-vulnerability scan in `onmc audit`** — the missing third scan type (semgrep=SAST, gitleaks=secrets, **osv=dependency CVEs**). With `--osv` (default off) and the `osv-scanner` binary on PATH, audit runs OSV against the project and folds CVE findings into the report/score (HIGH −15, CRITICAL −25). `shutil.which` detection (no pip dep), injectable runner, unchanged when absent. Completes the supply-chain story alongside `onmc sbom`.
- **Optional fastembed cross-encoder reranker** — a real ONNX cross-encoder reranks recall candidates when the `fastembed` extra is installed and `ONMC_RERANKER=fastembed` is set; falls back silently to the existing cosine-blend heuristic otherwise (zero regression). Mirrors the `ONMC_EMBEDDER=fastembed` bi-encoder pattern.
- **`onmc wiki site [--out DIR] [--json]`** — exports memory as a self-contained, browsable static HTML site (index grouped by kind + one page per memory with resolved edge links), openable in any browser with no external app. Pure stdlib, inline CSS, deterministic — a distinct consumption model from the logseq/foam/obsidian vault exporters.

All three are optional / zero-dep additions with graceful fallback — built in parallel by an onmc swarm (planned by `onmc mission`), each its own PR (#204, #205, #206).

## [0.68.0] — 2026-07-04

### Added

- **`onmc twin` — repo digital-twin change rehearsal** — before an agent edits code, rehearse the change offline: predict the blast radius (dependents via `codegraph`), surface the covering tests to run, and flag high-risk hub files — analysis only, never runs or edits code. `twin plan <paths…>` and `twin rehearse <paths…>`, `--json`. The RL-style "rehearse before you touch prod" frontier, grounded in the structural code graph.
- **`onmc attest` — verifiable proof-of-work trust layer** — turns an onmc receipt into a signed, portable, ERC-8004-shaped attestation (HMAC-SHA256, constant-time verify) plus an agent reputation summary (verified-rate, distinct goals, track record). Stdlib-only, off-chain, unsigned-digest fallback when no secret. `attest sign/verify/reputation`, `--json`. Completes the receipts→trust story with `badge` (display) and `flywheel` (learn) — the agent-economy white space. (Code shipped in v0.67.0; documented here.)

Both built via the `onmc mission`→swarm dogfood loop, each its own verified PR (#203, #201) — onmc building onmc.

## [0.67.0] — 2026-07-04

### Added

- **Optional fastembed local ONNX embedder** — a real semantic embedder (CPU ONNX, no API key) available via the `fastembed` extra; opt in with `ONMC_EMBEDDER=fastembed`. Import-guarded, and silently falls back to the default zero-dep hash embedder when the extra is absent or not selected (no change to the default install). Closes the "hash embedder is weak" gap `onmc roast` flags.
- **SARIF 2.1.0 output for `onmc audit`** — `onmc audit --format sarif` emits findings as a valid SARIF 2.1.0 document (uploadable to GitHub code-scanning, viewable in the VS Code SARIF viewer), including any semgrep/gitleaks findings. Pure stdlib; the default Rich scorecard and `--json` output are unchanged.
- **`onmc sbom` — CycloneDX 1.5 SBOM** — generates a software bill of materials from `uv.lock` (falling back to `pyproject.toml`) with normalized purls and deterministic ordering. Pure stdlib (`tomllib`), no new dependency, `--out`/`--json`. New module via command auto-discovery.

All three are optional, import-guarded / zero-dep additions with graceful fallback — built in parallel by an onmc swarm (planned by `onmc mission`), each its own PR (#197, #198, #200).

## [0.66.0] — 2026-07-04

### Added

- **`onmc orggraph` — institutional-memory knowledge graph** — turns onmc's provenanced memories into an entity/relationship graph: extracts entities (files, components, decisions, people) and typed edges (`decided-by`, `supersedes`, `depends-on`, `caused-by`, `relates-to`), each carrying lineage (the source memory ids it came from). `orggraph build` materializes it, `orggraph query <entity>` shows neighbors + provenance, `orggraph why <decision>` traces a decision's lineage. Pure/deterministic/offline, `--json` on each. Targets the frontier's #1 2026 agent bottleneck — institutional memory that compounds.
- **`onmc flywheel` — self-improving trajectory analysis** — mines onmc's *verified* run receipts (the outcome-labeled trajectory data no other tool has) to compute which approaches win: per-model verified-rate, avg cost, avg wall-time, and a ranked recommendation ("for goals like X, prefer model Y — verified N/M at $Z"). Honest by construction: null cost is `n/a` never fabricated; below the sample floor it reports insufficient data. `--json`, `--since`.

Both built in parallel by an onmc swarm (planned by `onmc mission`), each its own verified PR — onmc building onmc.

## [0.65.0] — 2026-07-04

### Added

- **Optional gitleaks secret-scan in `onmc audit`** — with `--gitleaks` (default off) and the `gitleaks` binary on PATH, audit runs gitleaks and folds detected secrets into the report/score (critical severity deducts). `shutil.which` detection (no pip dep), injectable runner, audit unchanged when absent — a clean sibling to the semgrep integration.
- **`onmc wiki foam [--out DIR] [--json]`** — exports the memory store as a Foam workspace: one note per memory under `notes/` with YAML frontmatter, `[[wikilinks]]` for every edge kind, and an `index.md`. Pure stdlib, deterministic, no server — the YAML-frontmatter sibling of the Logseq exporter.
- **D2 output for `onmc viz` (`--format d2`)** — `onmc viz memory` and `onmc viz code` can emit [D2](https://terrastruct.com/d2) diagram text as an alternative to the default Mermaid. Pure stdlib sibling renderer; existing Mermaid output is unchanged.

All three are optional, import-guarded / zero-dep additions with graceful fallback — built in parallel by an onmc swarm (planned by `onmc mission`), each its own PR (#192–#194).

## [0.64.0] — 2026-07-04

### Added

- **Optional semgrep static-analysis in `onmc audit`** — with `--semgrep` (default off) and the `semgrep` binary on PATH, audit runs semgrep and folds its findings into the audit report/score. Detected via `shutil.which` (no pip dep); the real runner is injectable so core audit stays pure/offline; audit is unchanged when the binary is absent or the flag is off.
- **Optional ast-grep structural code-search in `onmc reuse`** — with `--ast-grep` (default off) and the `ast-grep`/`sg` binary on PATH, reuse-detection additionally surfaces structurally-similar code (AST-pattern matches) the text heuristic misses. `shutil.which` detection (no pip dep), injectable runner, unchanged when absent.
- **`onmc wiki logseq [--out DIR] [--json]`** — exports the memory store as a Logseq-compatible knowledge graph: one page per memory with Logseq `key:: value` properties, block/bullet formatting, and `[[wikilinks]]` for every memory-edge kind. Pure stdlib, deterministic, no server. `onmc wiki` is now a group; the bare command is preserved.

All three are optional, import-guarded integrations with graceful zero-dep fallback — built in parallel by an onmc swarm (planned by `onmc mission`), each its own PR (#186–#188).

## [0.63.0] — 2026-07-04

### Added

- **`onmc missioncontrol` — live swarm dashboard** — a read-only view of a running swarm: per-unit state (pending/queued/running/done/failed/aborted), receipt presence + `verified` flag + `diff_sha`, and the abort-sentinel state, read straight from the swarm manifest + tamper-evident receipts. `--all` lists every swarm; `--json` for machine consumption. Never mutates swarm state.
- **`onmc nightshift` — autonomous verified overnight swarm + morning digest** — plan a bounded, budget-capped backlog of swarm units (dry-run by default, spawns nothing), then render a morning report of what shipped, which units verified, and the PR links. Deterministic planner + receipt summariser.
- **`onmc badge` — No-Slop verified proof-of-work PR badge** — turns an onmc receipt (`git_tree_sha`, `diff_sha`, `verified`, `receipt_hash`) into a shareable shields.io badge, a shields endpoint JSON payload, and a tamper-evidence-forward PR-comment body. `--post N` publishes the proof comment on PR #N; `--json` emits the endpoint payload.

### Changed

- **`onmc mission` now decomposes by deliverable, not per context-file** — greenfield goals (building new modules) split into one unit per distinct deliverable instead of degenerating into N near-identical units scoped to unrelated context-pack files; change-work still scopes per file but is deduped and capped. A goal naming a real existing path is treated as change-work even with a build verb.

## [0.62.0] — 2026-06-24

### Added

- **Optional Ollama local LLM provider** — `ask`/`judge`/`solve`/`evolve` can run against a local Ollama server (stdlib urllib, no new dep, no API key, offline). Select via `onmc llm configure --provider ollama`; graceful when the server is absent.
- **Optional sqlite-vec semantic recall backend** — real vector KNN inside the existing `memory_vectors` table when the `sqlitevec` extra is installed; graceful fallback to the default hash embedder otherwise (zero behavioural change).
- **Optional tree-sitter multi-language codegraph** — `onmc codegraph` now indexes JS/TS/Go/Rust/Java (via the `treesitter` extra); falls back to Python-`ast` when absent (zero regression).

All three are optional, import-guarded integrations with graceful zero-dep fallback — and were built in parallel by an onmc swarm (planned by `onmc mission`), each its own PR.

## [0.61.0] — 2026-06-24

### Added

- **`onmc wrap` / `onmc unwrap`** — make onmc the default layer for Claude Code. `onmc wrap --strict` installs a PreToolUse Task-intercept (raw native agent spawns are denied + redirected to `onmc swarm`) and a UserPromptSubmit prompt-router (every prompt gets an onmc routing verdict via `route` + `guard`), plus a CLAUDE.md policy stanza. Self-exempting (onmc's own swarm fan-out is allowed via a fresh `.onmc/swarm/<id>/ACTIVE` marker or `ONMC_ALLOW_TASK=1`), `--soft` nudges instead of denying, hooks always exit 0 (never brick the CLI), and `onmc unwrap` perfectly reverses (restores settings.json + CLAUDE.md from backup).

## [0.60.0] — 2026-06-24

### Added

- **`onmc mission "<goal>"`** — the keystone: one command that composes the shipped pipeline (recall → pack → codegraph blast-radius → guard dead-ends → swarm plan) into a single mission plan + receipt. Plan-mode default (deterministic, offline, no agents); `--execute` hands off to the swarm. `--json`.
- **`onmc roast`** — viral repo agent-readiness score (0-100) blending hotspot memory coverage + audit grade + brain size + conventions, with blunt findings + an actionable next step. `--json`.
- **`onmc fix-ci <pr>`** — CI-fix autopilot: parses a failed PR's CI log → recalls related dead-ends → maps the error to likely-fix files (codegraph) → emits a fix plan. Plan-only; log injectable (offline). `--log`, `--json`.

All three built **in parallel by an onmc swarm** (one unit each, each self-registered via command auto-discovery with zero hub edits, each its own PR), then merged.

## [0.59.0] — 2026-06-24

### Fixed

- **Duplicate command-name guard** — `command_registry` detects + fails loudly on duplicate `onmc <name>` registrations (silent shadowing is gone); `detect_duplicate_commands(app)` is a CI guard.
- **cli-reference auto-discovery** — `generate-cli-reference.py` introspects the Typer app instead of a hardcoded COMMANDS list, so new features never edit it — removing the last shared hub for collision-free parallel PRs (also recovered 19 stale-missing commands).
- **preflight toolchain robustness** — `onmc preflight --provision` runs tools via `uv run --with` + pins typer for the cli-reference step, giving true results in fresh worktrees; `onmc swarm verify`/`--auto-verify` provision by default, unblocking the staff-engineer gate.

## [0.58.0] — 2026-06-24

### Added

- **`onmc pack`** — per-task context pack (dead-ends + decisions + reuse hints + tiny codegraph context) for grounding spawned agents.
- **`onmc contract init`** — spec-as-contract: emits a failing pytest skeleton + stub from a spec (enforced TDD).
- **`onmc proptest init`** — property/invariant test generator (fixed-seed, stdlib, no new deps).
- **`onmc inbox`** — ranked work queue from manual adds + TODO/FIXME + coverage gaps + memory.

All four built in parallel by an onmc swarm (each unit self-registered via command auto-discovery, zero hub-code edits, each its own PR), then integrated.

### Removed

- Legacy hub-wired `pack` command (superseded by the auto-discovery `onmc pack`; resolves a silent duplicate-command shadow).

## [0.57.0] — 2026-06-24

### Added

- **Swarm staff-engineer mode** — a swarm unit is "verified/done" only when it automatically passes the quality gate in its own worktree. `onmc swarm verify <id> <unit> --worktree <p> [--base main]` runs `onmc preflight` (ruff/mypy/cli-reference/pytest) + `onmc verify-diff` (real, non-empty, lawful diff); `onmc swarm record ... --auto-verify` sets the receipt's `verified` from the real gate (overriding any manual attestation — a lying `--verified` can't pass, and a passing test suite over an empty diff is NOT ok); `onmc swarm pr <id> <unit> --worktree <p>` opens a per-unit PR (PR-and-stop) and refuses an unverified unit. `plan_inline_swarm` gained optional per-unit `claim_paths` leases.

## [0.56.0] — 2026-06-27

### Added

- add context packs and fleet status (#143)

## [0.55.0] — 2026-06-24

### Added

- **Command auto-discovery registry** — the keystone for collision-free parallel feature development. New features self-register their CLI via `src/oh_no_my_claudecode/<feat>/commands.py` exposing `register(app)`; `command_registry.register_feature_commands(app)` discovers and wires them automatically. A feature now touches **zero shared hub files** (cli.py / core/service.py / rendering/console.py / generate-cli-reference.py), so parallel agents can each own a feature and open conflict-free PRs. Purely additive — the existing ~70 registrations are untouched. CONTRIBUTING.md documents the convention.

## [0.54.0] — 2026-06-24

### Added

- **`onmc preflight`** — runs the exact CI gate locally (ruff / mypy --strict / cli-reference --check / pytest, in CI order) with an injectable runner, so any agent validates the way CI does. `--only`, `--json`.
- **`onmc verify-diff`** — adversarial diff-level gate: passes only when the diff is real (non-empty), introduces every expected symbol/file, is covered, and is lawful (no banned/secret patterns in added lines). Closes the empty-diff false-converge. `--base`, `--expect-symbol`, `--expect-file`, `--json`.
- **`onmc ledger`** — agent-work accounting (cost / wall-time / success-rate / ROI) over the run receipts that loop + swarm write. Honest: null cost is reported as n/a, never fabricated. `today`/`project`/`roi`, `--json`.
- **`onmc release`** — drafts the next CHANGELOG entry + proposes the semver bump from conventional-commit subjects since the last tag. `--dry-run`/`--write`; never tags or pushes.

All deterministic, offline, no schema migration. Built in parallel by onmc's token-free in-session swarm.

## [0.52.1] — 2026-06-27

### Fixed

- **Codex process swarms can now write inside isolated worktrees.** The Codex
  loop adapter now runs `codex exec --sandbox workspace-write ...` instead of a
  bare `codex exec`, because non-interactive Codex defaults to a read-only
  sandbox on this machine. This unblocks `onmc swarm run --agent codex` for real
  feature work while preserving worktree isolation.

## [0.52.0] — 2026-06-27

### Added

- **Agent Ops batch 1 — codegraph, reuse radar, and conventions.** `onmc codegraph`
  builds a deterministic structural repo graph for smaller, smarter agent context
  (`summary`, `neighbors`, `context`). `onmc reuse "<query>"` scans existing
  functions/classes so agents stop reimplementing patterns already in the repo.
  `onmc conventions capture/show` records repo conventions into `.onmc/conventions.md`
  so spawned agents inherit style, test, and tooling expectations. This batch was
  built through the token-free in-session swarm and shipped with dedicated tests.

## [0.51.0] — 2026-06-27

### Added

- **In-session subagent swarm — token-free parallel fan-out.** A second swarm execution model alongside the process swarm. Instead of shelling out to N independent `claude -p` processes (each of which must authenticate on its own), the inline swarm is driven by the Claude Code session itself: the model fans workers out as **subagents (Task tool)** that inherit the session's authentication — **no API key or OAuth token is needed.** onmc is the accountability ledger, not the spawner. `onmc swarm plan --file tasks.txt --json` allocates a swarm id + manifest (`mode="inline"`, units pending) and returns the abort-sentinel path; Claude Code fans the subagents out and reports each back with `onmc swarm record <id> <unit> --goal … --summary … [--verified] [--files …]`, which writes a tamper-evident receipt per unit (reuses `build_receipt` — git tree/diff SHA, hash chain, reproducibility envelope) and atomically updates the manifest. Honest status: a unit is `done` only with `--verified`. Inline + process swarms share the `.onmc/swarm/<id>/` layout, so `onmc swarm status/list/abort` work identically for both. The `/onmc-swarm` slash command now defaults to the token-free in-session path (fan out via the Task tool → record → summarize), with `--process` to fall back to the shell-out swarm. Trade-off: in-session is token-free but bounded by Claude Code's subagent cap (~10 concurrent, so it batches) with soft-abort; process mode scales further with hard-kill but needs a credential. Both produce the same auditable receipts.

### Fixed

- **Agent auth/API errors can never be reported as `verified`.** A headless `claude -p --output-format json` returns API failures (401 auth, 529 overload) *inside* a structurally-successful JSON envelope (`is_error: true` / `api_error_status`). The adapter previously parsed that error text as ordinary agent output, so a lenient verifier could let the loop "converge" on a run where the agent never authenticated — yielding a receipt that lied (`verified: true`) and a swarm unit reported `done`. Now: `AgentRunResult` carries an `error` field set by a new `_detect_claude_error()` (and on OS-level failures for the Codex/OpenCode adapters); the loop engine forces a loss and stops with `stop_reason="agent-error"` on any errored agent run (never a win, even if verify passes); and `run_swarm` reports a unit `done` **only** when its loop actually converged — any other terminal stop (agent-error, max-iterations, cost, circuit-breaker) is `failed`, never a silent `done`. Verified live: a real 2-unit swarm against an unauthenticated `claude` now reports both units failed/agent-error (was: silently done/verified).

### Added

- **`onmc swarm` — native parallel accountable agent fan-out.** Run many goals at once instead of one loop at a time: `onmc swarm run --file units.txt [--concurrency N]` (or repeated `--task`) launches a bounded worker pool, each unit running a full isolated `run_loop` in its own git worktree with its own tamper-evident receipt. Concurrency defaults to `min(cpu-1, 8)`; `--max-cost-usd` stops launching new units once the swarm's cumulative cost is exceeded. Swarm state persists to `.onmc/swarm/<id>/manifest.json`; `onmc swarm status <id>` / `onmc swarm list` report progress. `--json` everywhere for scripting. Works with claude / codex / opencode agent backends.
- **Hard abort.** `onmc swarm abort <id>` drops an `ABORT` sentinel that the loop's new `should_continue` hook checks before each iteration: the running unit stops with `stop_reason="aborted"`, queued units never start, and partial receipts are preserved. `/onmc-swarm` and `/onmc-abort` slash commands wire this into Claude Code.

### Added

- **`onmc nomistakes` — PR-ready No-Mistakes gate.** Composes the existing accountability stack into one CI/merge command: deterministic `audit` preflight, optional `eval` threshold, autonomy labels (`L0` observe, `L1` advise, `L2+` act+prove), isolated worktree execution by default, `autopilot` KNOW→PLAN→ACT→PROVE→LEARN, hard token/cost/wall limits, and a verified receipt as the only approval path. `onmc nomistakes "<goal>" --verify "pytest -q" [--agent claude|codex|opencode] [--eval-fail-under 80] [--plan-with ... --execute-with ...] [--json]`.
- **`onmc autopilot --isolate`.** Autopilot can now forward ACT into the existing loop worktree isolation path, so higher-level gates can keep failed agent edits away from the caller's working tree while preserving successful worktrees.

## [0.47.0] — 2026-06-24

### Added

- **Durable loop checkpoint/resume.** Each iteration atomically persists loop state to `.onmc/loop-state/`, so a crashed or interrupted `onmc loop`/`autopilot` run can `--resume` and continue from the next iteration with prior dead-ends and contracts intact (no repeated work). Checkpoints clear on terminal stops and are kept on resumable ones (budget/cost/wall). No `--resume` / no checkpoint = unchanged behavior.
- **Ready-to-run loop templates.** `onmc loop --template ci-healer | pr-babysitter | issue-to-pr` prefill goal + verifier + sane limits (overridable with explicit flags). `onmc loop --list-templates` / `onmc loop-templates` lists them.

## [0.46.0] — 2026-06-24

### Added

- **Loop token-storm circuit breaker.** Two tighter guards complement the existing no-progress/budget/cost/wall/max stops: `duplicate-action` (the same iteration signature repeats) and `repeated-error` (the same verify-error head repeats). The CLI/service enables sane defaults so `onmc loop`/`onmc autopilot` are protected from token storms out of the box (the raw engine keeps them off for backward-compat).
- **Worktree isolation + rollback.** `onmc loop --isolate` runs the agent in a fresh git worktree; on failure the worktree is removed (the caller's working tree stays clean), on success it is kept. Backed by an injectable isolation provider; git-worktree failure degrades gracefully to in-place.

## [0.45.0] — 2026-06-24

### Added

- **Plan→execute cost-split for `onmc autopilot`.** `--plan-with <model> --execute-with <model>` runs a new PLAN phase (KNOW→PLAN→ACT→PROVE→LEARN) where an expensive model writes a precise step-by-step plan; the plan is injected into the ACT goal and recorded as a memory, then the loop executes with the cheap model. `onmc evolution` proves the cost drop over time. Backward-compatible (no flags = current behavior); the plan step is exception-safe and dry-run-safe.

## [0.44.0] — 2026-06-24

### Added

- **Reproducibility envelope in the run receipt.** Receipts now prove a run is reproducible + auditable, not just verified: `RunReceipt` gains `model_version`, `prompt_hash`, `tool_defs_hash`, `config_hash`, `python_version`, and `platform` (deterministic hashes over the prompt, verifier/agent, and loop config). All fields are backward-compatible (None defaults; old receipts still parse). Receipt schema bumped 1→2; the CLI shows a `reproducible: model · config <hash> · prompt <hash>` line when present.

### Fixed

- The `greetings` workflow no longer fails CI on maintainer PRs — it now greets only fork PRs and issues (with a safety net), and dropped a bogus `onmc --version` reference.

## [0.43.0] — 2026-06-24

### Added

- **First-class OpenCode support.** `onmc loop`/`onmc autopilot --agent opencode` drives OpenCode headless (`opencode run --format json [--model provider/model]`) behind the injectable runner, with defensive output/token parsing and graceful missing-binary handling. `onmc plug opencode` writes an idempotent onmc stanza into `AGENTS.md` (coexisting with the codex stanza) plus a `.opencode/skills/` index, and is included in the `all` target. Reaches OpenCode's model-agnostic user base while keeping onmc's vendor-neutral, one-loop-any-agent posture.

## [0.42.0] — 2026-06-24

### Added

- **`onmc skill export` — official Agent Skills `SKILL.md` export.** Turns a repo's learned skills into portable `SKILL.md` files on the agentskills.io open standard, so they run across 16+ tools (Claude Code, Cursor, Codex, Gemini, Copilot, OpenCode, Goose, Letta, Hermes). Maps the onmc Skill to standard frontmatter (`name`, `description`, `when_to_use`←trigger, `paths`←files, with the 1,536-char combined cap) + body + provenance footer. `onmc skill export [--out DIR] [--scope project|personal] [--json]` writes `<slug>/SKILL.md` to `.claude/skills/` (project) or `~/.claude/skills/` (personal).

## [0.41.0] — 2026-06-24

### Added

- **Open-source community pack.** `CITATION.cff` (onmc is now citable), `.github/FUNDING.yml` (sponsor button), and three community-automation workflows: **greetings** (welcomes first-time issue/PR contributors), **stale** (ages out abandoned issues/PRs after 60d/+14d, exempting good-first-issue / help-wanted / pinned / security / needs-triage), and **labeler** + `.github/labeler.yml` (auto-applies area labels by changed path). All workflows use read-only default permissions, job-scoped writes, and pinned action SHAs.

## [0.40.0] — 2026-06-24

### Fixed

- **Friendly errors on first contact.** Running any onmc command outside a git repository now prints a clean `✗ Not inside a git repository. cd into your project (or git init) and run onmc setup.` and exits 1 — instead of dumping a raw `RepoDiscoveryError` traceback.
- **`onmc setup` works in git worktrees.** Setup (and all hook installers) no longer crash with `NotADirectoryError` in a linked worktree, where `.git` is a file. Hook directories are now resolved via `git rev-parse --git-path hooks`, correct for both normal repos and worktrees.

## [0.39.0] — 2026-06-24

### Added

- **Mission Control view in `onmc ui`** — completing the loop-closer trio (autopilot + evolution + Mission Control). The dashboard now both explains and shows the product: a KNOW → ACT → PROVE → LEARN loop strip, the "getting smarter" trend band from `onmc evolution` (↓cost / ↓iterations + verified-rate, with a friendly empty-state), and a recent-runs table that makes the receipt ledger visible (goal · agent · ✓/✗ · iterations · cost · when · receipt hash). Fed by a new exception-safe `loops` payload section (evolution summary + recent receipts); no receipts degrades to a clean empty-state. Self-contained, theme-matched, responsive.

## [0.38.0] — 2026-06-24

### Added

- **`onmc evolution` — compounding proof from the receipt chain.** Reads the run receipts that `onmc loop`/`onmc autopilot` write to `.agent-memory/receipts/` and shows the agent getting cheaper/smarter across runs: "↓X% cost · ↓Y% iterations-to-converge across N runs", with verified-rate and a per-run table. Honest by construction — every number comes from real receipts (no simulation), needs ≥2 receipts or it shows an insufficient-data prompt, cost trend only when cost is present, "iterations-to-converge" is labelled a proxy for wasted effort. Null timestamps and malformed receipts are handled gracefully. `onmc evolution [--json]`.

## [0.37.0] — 2026-06-24

### Added

- **`onmc autopilot "<goal>"` — one verb that closes the whole loop.** Orchestrates the existing commands into a single narrated run: 🧠 KNOW (`compile_brief` + `guard` dead-ends + `user_profile`) → ⚙ ACT (the memory-grounded loop with real claude/codex adapters + limits) → ✅ PROVE (tamper-evident receipt + VERIFIED verdict) → 📈 LEARN (on a win: capture the approach + promote a skill + consolidate; on a loss the loop records the dead-end). Ends with a "Your brain grew" delta (+N memories · +N skills · N dead-ends · $cost · receipt). `--dry-run` shows the KNOW context with zero spend; reuses all loop limits (`--max-cost-usd` / `--max-wall-seconds` / `--max-iterations` / `--verify`). `--json` for machine output.
- `service.loop()` now accepts optional injected agent/verify runners (default = build real), enabling composition + deterministic testing.

## [0.36.0] — 2026-06-24

### Added

- **Delightful onboarding across CLI and dashboard.** `onmc setup` is now a guided ride: a branded ANSI wordmark splash + version, a 6-step tracker (→ then ✓ per phase), honest staged scan progress, a "first win" panel that runs a real recall right after ingest to show what your repo already knows, a capabilities checklist (✓/○), a "what you can do now" card (brief / loop / why / ui), and a UI handoff (interactive mode offers to open the dashboard; `--yes`/non-interactive only prints a tip and never launches a server).
- **`onmc ui` first-run welcome overlay** — a dismissible, theme-matched welcome with live stats (memories / hotspots / decisions+invariants) and a 3-step "what now"; shows on a fresh brain, persists dismissal in localStorage, re-openable via a "?" affordance. Self-contained, responsive, reduced-motion aware.

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

- **`onmc eval` — memory evaluation + regression gate.** Proves the brain helps and blocks regressions in CI (the 2026 evals trend). An eval case is a query + expected memory behavior, scored with onmc's own retrieval: correct-files-surfaced (`compile_recall` top-K hit) and failed-path-avoided (`compile_guard` surfaces the known dead-end), plus injected cost. Running with-memory vs without-memory yields a measurable score delta. `onmc eval create --from-memory <id>` (cases stored as JSON under `.onmc/evals/`), `onmc eval run [--without-memory] [--fail-under <pct>] [--json]`, `onmc eval compare [--baseline <pct>] [--json]`; `--fail-under`/`--baseline` exit nonzero below threshold so it drops into CI as a regression gate. Deterministic, offline, no LLM, no schema migration.

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
