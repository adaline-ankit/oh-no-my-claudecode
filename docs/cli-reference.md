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
│ memory-diff  Show what repo knowledge changed between two commits.           │
│ digest       Show what the repo/team learned since a git ref.                │
│ guard        Surface recorded dead-ends so you never repeat a known failure. │
│ recall       Search memory for past incidents matching an error or           │
│              stacktrace.                                                     │
│ check        Flag staged/changed files that touch recorded invariants or     │
│              dead-ends.                                                      │
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
│ wiki         Generate a browsable multi-page markdown wiki from stored       │
│              memory.                                                         │
│ bench        Measure whether onmc memory actually reduces wasted work.       │
│ plug         Wire onmc into a target coding agent (one-shot idempotent       │
│              wizard).                                                        │
│ memory       Inspect stored memory.                                          │
│ spec         Inspect and validate the Agent Memory open spec.                │
│ task         Manage task lifecycle state.                                    │
│ attempt      Track task-scoped attempts.                                     │
│ llm          Configure optional LLM providers.                               │
│ hooks        Install and run Claude Code compaction hooks.                   │
│ claude-md    Generate and maintain CLAUDE.md from ONMC memory.               │
│ playbook     Synthesize and manage memory-derived playbooks.                 │
│ user         Manage cross-repo user preferences (stored in ~/.onmc, not      │
│              repo-scoped).                                                   │
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
Usage: onmc pull [OPTIONS] SOURCE                                              
                                                                                
 Import another repo's .agent-memory/ export into this brain (federated         
 memories).                                                                     
                                                                                
 Federated memories are tagged ``federated:<repo-label>`` so they are clearly   
 attributed to their source and are never confused with local memories.         
 Re-pulling is idempotent: memories already present are skipped.                
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    source      PATH  Path to another repo (or its .agent-memory/ dir) to   │
│                        import from.                                          │
│                        [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --label        TEXT  Override the short repo label used for the              │
│                      federated:<label> tag. Defaults to the source directory │
│                      name.                                                   │
│ --json               Emit a machine-readable JSON summary to stdout.         │
│ --help               Show this message and exit.                             │
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

## `onmc wiki`

```text
Usage: onmc wiki [OPTIONS]                                                     
                                                                                
 Generate a browsable multi-page markdown wiki from stored memory.              
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --output        PATH  Directory to write wiki pages into. Defaults to        │
│                       .onmc/wiki/ (gitignored). Pass e.g. docs/wiki to       │
│                       produce a committable copy.                            │
│ --help                Show this message and exit.                            │
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
