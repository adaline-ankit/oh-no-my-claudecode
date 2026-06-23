# CLI Reference

This file is generated from Typer help output.
Run `python scripts/generate-cli-reference.py` after changing CLI commands.

## `onmc`

```text
Usage: onmc [OPTIONS] COMMAND [ARGS]...

 Repo-native memory and context compiler for coding agents.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --install-completion          Install completion for the current shell.      │
│ --show-completion             Show completion for the current shell, to copy │
│                               it or customize the installation.              │
│ --help                        Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ tui          Open the interactive terminal brain-browser for memory          │
│              curation.                                                       │
│ setup        Run the interactive ONMC onboarding wizard.                     │
│ init         Initialize ONMC state in the current git repository.            │
│ ingest       Ingest repo knowledge into local structured memory.             │
│ brief        Compile a task-specific context brief.                          │
│ codegraph    Generate a compact codegraph for token-efficient agent          │
│              navigation.                                                     │
│ why          Explain why a file looks the way it does, from memory + git     │
│              history.                                                        │
│ onboard      Give a new dev (or agent) the guided five-minute repo tour from │
│              memory.                                                         │
│ blame        Git blame for knowledge: map a file's symbols to the memories   │
│              that govern them.                                               │
│ coverage     Show a knowledge-gap dashboard: coverage % + uncovered hotspot  │
│              files.                                                          │
│ memory-diff  Show what repo knowledge changed between two commits.           │
│ digest       Show what the repo/team learned since a git ref.                │
│ guard        Surface recorded dead-ends so you never repeat a known failure. │
│ recall       Search memory for past incidents matching an error or           │
│              stacktrace.                                                     │
│ ask          Ask a natural-language question answered from repo memory.      │
│ check        Flag staged/changed files that touch recorded invariants or     │
│              dead-ends.                                                      │
│ ui           Open the local read-only ONMC visual dashboard.                 │
│ status       Show local ONMC status.                                         │
│ statusline   Print a compact one-line brain health string for Claude Code    │
│              statusLine.                                                     │
│ hud          Display a rich multi-line memory health HUD panel.              │
│ report       Generate a shareable agent-readiness report.                    │
│ sync         Export, restore, or hook git-portable ONMC memory state.        │
│ pull         Import another repo's .agent-memory/ export into this brain     │
│              (federated memories).                                           │
│ serve        Serve ONMC over the requested runtime protocol.                 │
│ solve        Compile repo-aware context and ask the configured LLM for the   │
│              next best approach.                                             │
│ review       Compile repo-aware review context and critique the proposed     │
│              approach.                                                       │
│ teach        Compile repo-aware teaching context and generate a learning     │
│              artifact.                                                       │
│ consolidate  Clean and strengthen the memory store (dedup, merge,            │
│              promote/demote, edge graph).                                    │
│ mine         Mine Claude Code session transcripts into ONMC memory.          │
│ capture      Heuristically capture durable memory from a session transcript. │
│ doctor       Run a health check over repo state, memory, provider setup, and │
│              integrations.                                                   │
│ audit        Scan agent configuration for security risks and emit a scored   │
│              report.                                                         │
│ wiki         Generate a markdown wiki or Obsidian knowledge-graph vault.     │
│ bench        Measure whether onmc memory actually reduces wasted work.       │
│ savings      Show a shareable 'Memory Wrapped' token-ROI card.               │
│ benchmark    Run a reproducible benchmark suite against the current repo     │
│              brain.                                                          │
│ plug         Wire onmc into a target coding agent (one-shot idempotent       │
│              wizard).                                                        │
│ feedback     Apply a human trust signal to a stored memory.                  │
│ import       Import skills or memories from an external tool into the ONMC   │
│              brain.                                                          │
│ loop         Run a memory-grounded autonomous loop that avoids recorded      │
│              dead-ends.                                                      │
│ memory       Inspect stored memory.                                          │
│ spec         Inspect and validate the Agent Memory open spec.                │
│ task         Manage task lifecycle state.                                    │
│ attempt      Track task-scoped attempts.                                     │
│ llm          Configure optional LLM providers.                               │
│ hooks        Install and run Claude Code compaction hooks.                   │
│ claude-md    Generate and maintain CLAUDE.md from ONMC memory.               │
│ playbook     Synthesize and manage memory-derived playbooks.                 │
│ skill        Manage self-improving skills synthesized from playbooks and     │
│              memory patterns.                                                │
│ user         Manage cross-repo user preferences (stored in ~/.onmc, not      │
│              repo-scoped).                                                   │
│ profile      Show and rebuild the derived user behavioral profile            │
│              (~/.onmc/user.db).                                              │
│ notify       Inspect and test the context firewall notification sink.        │
│ trace        Agent Trace Observatory — instrument a session and get a        │
│              token-ROI report.                                               │
│ eval         Measure and gate memory recall quality (offline,                │
│              deterministic).                                                 │
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

## `onmc init`

```text
Usage: onmc init [OPTIONS]

 Initialize ONMC state in the current git repository.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
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

## `onmc codegraph`

```text
Usage: onmc codegraph [OPTIONS]

 Generate a compact codegraph for token-efficient agent navigation.

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
│   query      [QUERY]  Error text or stacktrace to search for. Omit to read   │
│                       from stdin (pipe-friendly: `cmd 2>&1 | onmc recall`).  │
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

## `onmc hud`

```text
Usage: onmc hud [OPTIONS]

 Display a rich multi-line memory health HUD panel.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
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
│   source      [SOURCE]  Local path to another repo (or its .agent-memory/    │
│                         dir), or a remote git URL (https://, git@, ssh://).  │
│                         Omit when using --all.                               │
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

## `onmc doctor`

```text
Usage: onmc doctor [OPTIONS]

 Run a health check over repo state, memory, provider setup, and integrations.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
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

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      [PATH]  Repo root to scan.  Defaults to the current directory.   │
│                     The directory does not need to be an initialised ONMC    │
│                     repo — audit is purely static.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                 Emit the full AuditReport as JSON to stdout.          │
│ --fail-on        TEXT  Exit non-zero when at least one finding at this       │
│                        severity or higher exists.  One of: critical, high,   │
│                        medium, low, info.  Default: high.                    │
│                        [default: high]                                       │
│ --help                 Show this message and exit.                           │
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

## `onmc llm status`

```text
Usage: onmc llm status [OPTIONS]

 Show optional LLM provider configuration status.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc llm configure`

```text
Usage: onmc llm configure [OPTIONS]

 Persist optional LLM provider settings to the local ONMC config.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --provider               [anthropic|openai|mock]  LLM provider to         │
│                                                      configure.              │
│                                                      [required]              │
│ *  --model                  TEXT                     Default model name.     │
│                                                      [required]              │
│    --api-key-env-var        TEXT                     Environment variable to │
│                                                      read the provider API   │
│                                                      key from.               │
│    --temperature            FLOAT RANGE              Default temperature.    │
│                             [0.0<=x<=2.0]            [default: 0.0]          │
│    --max-tokens             INTEGER RANGE [x>=1]     Default maximum output  │
│                                                      tokens.                 │
│                                                      [default: 1024]         │
│    --help                                            Show this message and   │
│                                                      exit.                   │
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
│ install        Install project-scoped Claude Code hooks into                 │
│                .claude/settings.json.                                        │
│ uninstall      Remove ONMC entries from project Claude Code settings and     │
│                .mcp.json.                                                    │
│ status         Show current Claude hook installation and snapshot status.    │
│ pre-compact    Capture a compaction snapshot before Claude Code compacts     │
│                context.                                                      │
│ session-start  Inject context at session start: boot digest on startup,      │
│                continuation brief after compaction.                          │
│ prompt-recall  Inject the most relevant repo memories for the current user   │
│                prompt.                                                       │
│ session-end    Run memory consolidation and heuristic auto-capture on        │
│                SessionEnd.                                                   │
│ pre-tool-use   Inject file-level danger warnings before the agent edits a    │
│                file.                                                         │
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

## `onmc hooks uninstall`

```text
Usage: onmc hooks uninstall [OPTIONS]

 Remove ONMC entries from project Claude Code settings and .mcp.json.

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

## `onmc hooks pre-compact`

```text
Usage: onmc hooks pre-compact [OPTIONS]

 Capture a compaction snapshot before Claude Code compacts context.

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

## `onmc claude-md update`

```text
Usage: onmc claude-md update [OPTIONS]

 Update stale CLAUDE.md sections.

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
│   playbook_id      [PLAYBOOK_ID]  Playbook ID (or prefix) to promote to a    │
│                                   skill.                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --auto              Auto-detect recurring patterns and promote all.          │
│ --name        TEXT  Override the skill name (only used with a playbook-id).  │
│ --json              Emit the new skill(s) as JSON.                           │
│ --help              Show this message and exit.                              │
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

## `onmc tui`

```text
Usage: onmc tui [OPTIONS]

 Open the interactive terminal brain-browser for memory curation.

╭─ Options ────────────────────────────────────────────────────────────────────╮
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

## `onmc loop`

```text
Usage: onmc loop [OPTIONS]

 Run a memory-grounded autonomous loop that avoids recorded dead-ends.

 Each iteration recalls FAILED_APPROACH memories so the agent cannot repeat
 known dead-ends.  Wins are recorded as DECISION memories; losses are
 recorded as FAILED_APPROACH memories so future iterations block them.


 Examples
 --------
 onmc loop --goal "fix the cache invalidation bug" --verify "pytest tests/"
 onmc loop --goal "fix the bug" --agent codex --verify "pytest tests/"
 onmc loop --spec goal.txt --max-iterations 5 --budget-tokens 50000
 onmc loop --goal "refactor auth module" --dry-run          # preview prompt
 only
 onmc loop --goal "fix flaky test" --json                   # machine-readable
 output

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --goal                  TEXT                  Goal text for the loop         │
│                                               (inline).                      │
│ --spec                  TEXT                  Path to a file containing the  │
│                                               goal text.                     │
│ --agent                 TEXT                  Agent CLI to use: claude       │
│                                               (default) or codex.            │
│                                               [default: claude]              │
│ --max-iterations        INTEGER RANGE [x>=1]  Maximum loop iterations.       │
│                                               [default: 10]                  │
│ --budget-tokens         INTEGER RANGE [x>=1]  Stop when total tokens exceed  │
│                                               this budget.                   │
│ --verify                TEXT                  Shell command run after each   │
│                                               iteration to verify success.   │
│                                               [default: pytest]              │
│ --dry-run                                     Build the prompt and recall    │
│                                               dead-ends without invoking the │
│                                               agent or verify. Safe to run   │
│                                               without any configured agent.  │
│ --json                                        Print the full result as JSON. │
│ --help                                        Show this message and exit.    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `onmc wiki`

```text
Usage: onmc wiki [OPTIONS]

 Generate a markdown wiki or Obsidian knowledge-graph vault.

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
 cursor        Write/refresh .cursor/rules/onmc.md (Cursor >=0.40 format).
 omc           Write docs/integrations/omc.md with a copy-paste OMC adapter.
 omx           Write docs/integrations/omx.md with a copy-paste OMX adapter.
 all           Apply claude-code + codex + cursor (safe subset).

 All writes are idempotent — running twice never duplicates stanzas.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    target      TEXT  Agent to wire onmc into. Choices: claude-code, codex, │
│                        cursor, omc, omx, all.                                │
│                        [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
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
│ *    source      TEXT    Source to import from. Use 'omc' for                │
│                          oh-my-claudecode skills, 'hermes' for Nous          │
│                          hermes-agent context files, or a path to a .md file │
│                          / directory.                                        │
│                          [required]                                          │
│      path        [PATH]  Optional path override. For 'omc': path to          │
│                          .omc/skills dir. For 'hermes': path to MEMORY.md /  │
│                          USER.md / containing directory. For generic         │
│                          markdown: the .md file or directory (use as         │
│                          'source' instead).                                  │
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
│   session_id      [SESSION_ID]  Session ID to report on.  Defaults to the    │
│                                 current active session.                      │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json              Print machine-readable JSON to stdout.                   │
│ --otel        FILE  Write OpenTelemetry GenAI span JSON to this file path.   │
│ --help              Show this message and exit.                              │
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
