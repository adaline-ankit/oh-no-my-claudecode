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
│ setup      Run the interactive ONMC onboarding wizard.                       │
│ init       Initialize ONMC state in the current git repository.              │
│ ingest     Ingest repo knowledge into local structured memory.               │
│ brief      Compile a task-specific context brief.                            │
│ status     Show local ONMC status.                                           │
│ sync       Export, restore, or hook git-portable ONMC memory state.          │
│ serve      Serve ONMC over the requested runtime protocol.                   │
│ solve      Compile repo-aware context and ask the configured LLM for the     │
│            next best approach.                                               │
│ review     Compile repo-aware review context and critique the proposed       │
│            approach.                                                         │
│ teach      Compile repo-aware teaching context and generate a learning       │
│            artifact.                                                         │
│ mine       Mine Claude Code session transcripts into ONMC memory.            │
│ doctor     Run a health check over repo state, memory, provider setup, and   │
│            integrations.                                                     │
│ memory     Inspect stored memory.                                            │
│ task       Manage task lifecycle state.                                      │
│ attempt    Track task-scoped attempts.                                       │
│ llm        Configure optional LLM providers.                                 │
│ hooks      Install and run Claude Code compaction hooks.                     │
│ claude-md  Generate and maintain CLAUDE.md from ONMC memory.                 │
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
│ *  --task          TEXT  Task description to compile a brief for. [required] │
│    --no-llm              Skip the optional LLM reranking pass.               │
│    --help                Show this message and exit.                         │
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
│ session-start  Inject the continuation brief when a session starts after     │
│                compaction.                                                   │
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
                                                                                
 Inject the continuation brief when a session starts after compaction.          
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
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
│                                  thub_pr]                                    │
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
