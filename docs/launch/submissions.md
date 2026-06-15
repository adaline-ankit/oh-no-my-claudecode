# Ecosystem-List Submission Materials

Ready-to-paste submission materials for each target list. For every target: the
real repo + file + section, the exact entry text in their format, how to submit,
and acceptance status. The human decides whether/when to fire each off.

---

## 1. punkpeye/awesome-mcp-servers

**Repo:** https://github.com/punkpeye/awesome-mcp-servers  
**Target file:** `README.md`  
**Section:** `### 🧠 Knowledge & Memory` (alphabetical position: between `oh-*`
entries near the `o` block — insert before any `p*` entry)  
**Accepts external entries:** YES — straightforward fork-and-PR, no star floor,
maintainer is active.

### Researched format

Entries follow this pattern (drawn from live section):

```
- [owner/repo](https://github.com/owner/repo) 🐍 🏠 🍎 🪟 🐧 - Description sentence ending with period.
```

Icon legend used in the section:
- `🐍` Python · `📇` TypeScript/JS · `🦀` Rust · `🏎️` Go
- `🏠` local/self-hosted · `☁️` cloud/hosted
- `🍎` macOS · `🪟` Windows · `🐧` Linux

onmc: Python (`🐍`), local-only (`🏠`), macOS+Linux primary, Windows smoke-test
(`🍎 🪟 🐧`). No Glama badge yet (the project is not registered on glama.ai).

### Exact entry

```markdown
- [adaline-ankit/oh-no-my-claudecode](https://github.com/adaline-ankit/oh-no-my-claudecode) 🐍 🏠 🍎 🪟 🐧 - Git-portable cross-agent memory brain for coding agents. Stores decisions, invariants, and failed approaches in a committed `.agent-memory/` JSON store; injects the right knowledge at session start and before context compaction. MCP tools (`search_memory`, `guard_task`, `get_brief`), failure-aware recall via `onmc guard`, and one-command wiring into Claude Code, Cursor, and Codex. Open AGENT-MEMORY-SPEC for interoperability. `pip install oh-no-my-claudecode`
```

### How to submit

1. Fork `punkpeye/awesome-mcp-servers`.
2. Edit `README.md`; find `### 🧠 Knowledge & Memory`; insert the entry above in
   alphabetical order by repo name (after `adobe*`, before `ag*` — `adaline-ankit`
   sorts near the top of the section).
3. Commit: `Add oh-no-my-claudecode to Knowledge & Memory`.
4. Open PR against `main`.

**Contribution rules:** maintain alphabetical order within category; one server
per line; concise accurate description; no star minimum stated. For fast-track
merging, append `🤖🤖🤖` to the PR title (their opt-in for automated agents).

### Ready-to-paste PR title and body

**PR title:**
```
Add oh-no-my-claudecode to Knowledge & Memory
```

**PR body:**
```markdown
## Summary

Adds [oh-no-my-claudecode (onmc)](https://github.com/adaline-ankit/oh-no-my-claudecode)
to the 🧠 Knowledge & Memory section.

**What it is:** A git-portable, cross-agent memory brain for coding agents. Stores
structured knowledge (decisions, invariants, failed approaches) in a committed
`.agent-memory/` directory (plain JSON). MCP server exposes `search_memory`,
`guard_task`, and `get_brief` tools. `onmc guard` surfaces recorded dead-ends
before an agent starts a task so it never retries a known failed approach. One-command
wiring into Claude Code, Cursor, and Codex via `onmc plug <agent>`.

**Checklist:**
- [x] Alphabetical order within section maintained
- [x] Entry follows existing format (Python icon, local icon, OS icons, description ends with period)
- [x] Links are publicly accessible
- [x] PyPI package: `pip install oh-no-my-claudecode`
- [x] Open-source, MIT license
```

---

## 2. agamm/awesome-ai-sre

**Repo:** https://github.com/agamm/awesome-ai-sre  
**Target file:** `README.md`  
**Section:** `LLM-Powered DevOps Tools` (alphabetical position among `o` entries —
`oh-no-my-claudecode` sorts after `O`-named tools, before `P`)  
**Accepts external entries:** YES — PRs accepted; contributing.md is explicit.

### Researched format

Entries are **bullet + linked name + dash + one-sentence description ending with
period**. Table format is NOT used in README (the contributing.md template said
`| [Name](URL) | Description |` but the live README uses the bullet format below):

```
- [ToolName](URL) - One-sentence description of core function with 2-3 specific features.
```

### Qualification note

The contributing.md states: open source projects require **50+ stars or affiliation
with a recognized foundation (CNCF, Linux Foundation, etc.)**. onmc is a new
project and likely below 50 stars at launch. This is the primary risk for
acceptance — the maintainer may reject on that basis. The entry text is prepared
for when the threshold is met or waived at maintainer discretion.

### Exact entry

```markdown
- [oh-no-my-claudecode (onmc)](https://github.com/adaline-ankit/oh-no-my-claudecode) - Git-portable cross-agent memory brain that stores decisions, invariants, and recorded dead-ends in a committed `.agent-memory/` directory, injects relevant context before each Claude Code session and compaction, and exposes MCP tools for failure-aware recall so agents never repeat a known failed approach.
```

### How to submit

1. Fork `agamm/awesome-ai-sre`.
2. Edit `README.md`; find the `LLM-Powered DevOps Tools` section; insert the
   entry in alphabetical order by tool name (`oh-no-my-claudecode` after any `N`
   tools and before any `P` tools).
3. Commit: `Add oh-no-my-claudecode to LLM-Powered DevOps Tools`.
4. Open PR with title matching pattern shown in contributing.md: `Add ToolName to
   LLM-Powered DevOps Tools`.

**Contribution rules (from contributing.md):** entries in alphabetical order;
one entry per PR preferred; open source needs 50+ stars or foundation affiliation;
tool must be actively maintained; descriptions must be a single sentence ending
with a period.

### Ready-to-paste PR title and body

**PR title:**
```
Add oh-no-my-claudecode to LLM-Powered DevOps Tools
```

**PR body:**
```markdown
## Summary

Adds [oh-no-my-claudecode (onmc)](https://github.com/adaline-ankit/oh-no-my-claudecode)
to the LLM-Powered DevOps Tools section.

**What it is:** A git-portable memory layer for AI coding agents (Claude Code,
Cursor, Codex). Stores structured knowledge — decisions, architectural invariants,
and recorded failed approaches — as committed JSON in `.agent-memory/`. Exposes
an MCP server with `search_memory`, `guard_task`, and `get_brief` tools. The
`onmc guard` command surfaces recorded dead-ends before a task starts so agents
never repeat a known failed approach. Context survives compaction via Claude Code
hooks. One-command integration: `onmc plug claude-code`.

**Why this section:** It's an LLM-powered tool that improves DevOps/engineering
agent effectiveness by giving agents persistent, provenance-tracked memory across
sessions.

**Checklist:**
- [x] Alphabetical order maintained
- [x] Single sentence description ending with period
- [x] Actively maintained (see CHANGELOG — multiple releases in 2026)
- [x] MIT license, publicly accessible links
```

---

## 3. hesreallyhim/awesome-claude-code

**Repo:** https://github.com/hesreallyhim/awesome-claude-code  
**Target file:** `THE_RESOURCES_TABLE.csv` (entries are bot-managed from there
into README; humans do NOT edit either file directly)  
**Section:** Category `Agent Skills` (the maintainer is currently lumping plugins
under Agent Skills pending a reclassification; a `Workflows & Knowledge Guides`
category also exists and may be appropriate once the new org system ships)  
**Accepts external entries:** YES — via GitHub Web UI issue form only. PRs are
explicitly not the submission path; bots handle PRs.

### Critical process note

**Submissions MUST be made using the GitHub Web UI issue form at:**
https://github.com/hesreallyhim/awesome-claude-code/issues/new?template=recommend-resource.yml

The `gh` CLI cannot be used (submissions via CLI are automatically closed and may
incur a ban). The entry text below is for filling out that form's fields — not
for pasting into a PR.

### Form field values (exact, ready to copy-paste into the web form)

**Display Name:**
```
oh-no-my-claudecode (onmc)
```

**Category:** `Agent Skills`

**Primary Link:**
```
https://github.com/adaline-ankit/oh-no-my-claudecode
```

**Author Name:** `adaline-ankit`

**Author Link:** `https://github.com/adaline-ankit`

**License:** `MIT`

**Description (1-3 sentences, no emojis, descriptive not promotional):**
```
A git-portable, cross-agent memory brain for coding agents — stores decisions,
invariants, and recorded failed approaches as committed JSON in `.agent-memory/`,
injects relevant context at every Claude Code session start and before each
compaction, and surfaces known dead-ends via `onmc guard` so the agent never
retries a recorded failed approach. Integrates with Claude Code via hooks and
an MCP server (`search_memory`, `guard_task`, `get_brief`); also wires into
Cursor and Codex via `onmc plug <agent>`. Ships an open AGENT-MEMORY-SPEC so
any tool can read and write the same memory store.
```

**Validate Claims (how to prove it works):**
```
Clone the repo, install (`pip install oh-no-my-claudecode`), and run `onmc bench`
in any directory. The built-in deterministic benchmark runs with no LLM and no
network access and prints a before/after table showing repeated-failure rate 100%
→ 0% and context tokens −97% on the synthetic 5-task scenario. For live
integration: run `onmc setup` in a git repo, then `onmc plug claude-code` to
install hooks and MCP; open Claude Code and observe the boot digest injected at
session start.
```

**Specific Task:**
```
After `onmc setup` + `onmc plug claude-code`, open Claude Code in the repo and
give it a task that you have previously attempted. Observe that the session-start
hook injects a compact digest of stored decisions and recorded failed approaches
before the agent begins.
```

**Specific Prompt:**
```
"What do you know about this codebase? Summarize any recorded failed approaches
and key architectural decisions."
```

### How to submit

Open the form at:
https://github.com/hesreallyhim/awesome-claude-code/issues/new?template=recommend-resource.yml

Fill in the fields above using the GitHub Web UI. The automated bot validates the
form and posts results as a comment. Do not open a PR.

**Quality bar notes from CONTRIBUTING.md:** claims must be evidence-based
(the `onmc bench` deterministic benchmark satisfies this); security-sensitive
network calls must be disclosed (onmc is local-only by default; LLM provider
calls are opt-in and logged); resources must be at least one week old; maintainer
values focused, differentiated tools.

---

## 4. Jun-jie-Huang/awesome-LLM-AIOps

**Repo:** https://github.com/Jun-jie-Huang/awesome-LLM-AIOps  
**Target file:** `README.md`  
**Section:** This list is **academic papers only** — all entries are conference
or preprint papers with badge-tagged citations. It has no tools or open-source
projects section. onmc is an open-source CLI tool, not an academic paper, and
does not fit the list's scope.  
**Accepts external entries:** Yes for papers; unclear/no for tools.

### Assessment

The list's three sections (Incident Management, Log Analysis, Infrastructure
Management) exclusively contain peer-reviewed or preprint papers with venue
tags like `[ICSE 2023]`, `[EuroSys 2024]`, etc. Tool entries appear only as
project links embedded inside a paper's citation, never standalone. There is
no "Tools" or "Open-source Projects" section and the contribution guide
explicitly focuses on the paper format.

**Verdict: onmc does not fit this list in its current scope.** The entry text
below is provided for completeness in case the maintainer decides to add a tools
section in future, or if a future academic paper citing onmc's open AGENT-MEMORY-SPEC
becomes submittable.

### Entry text (if a tools section is added in future)

```markdown
- [oh-no-my-claudecode](https://github.com/adaline-ankit/oh-no-my-claudecode) [[onmc](https://pypi.org/project/oh-no-my-claudecode/)]. ![](https://img.shields.io/badge/onmc-blue) ![](https://img.shields.io/badge/Agent_Memory-brown) ![](https://img.shields.io/badge/Cross--Agent-green)
```

### How to submit (if scope expands)

Fork → edit `README.md` → add to a new "Tools & Open-Source Projects" section →
PR. The maintainer's contribution guide says "Don't worry if you put all these
wrong, we will fix them for you" — low friction once a section exists.

---

## 5. oh-my-claudecode (Yeachan-Heo/oh-my-claudecode) and oh-my-codex (Yeachan-Heo/oh-my-codex)

**Repos:**
- https://github.com/Yeachan-Heo/oh-my-claudecode (OMC) — 36k+ stars
- https://github.com/Yeachan-Heo/oh-my-codex (OMX) — 31k+ stars

**Accepts external entries:** UNCLEAR / likely no formal registry yet.

### Assessment

Neither OMC nor OMX has a community plugins registry, ecosystem page, or
curated list of third-party integrations that accepts external submissions.
Their `docs/integrations.html` is a collection of internal setup guides (Discord,
OpenClaw), not a directory of third-party tools. `CONTRIBUTING.md` describes
how to develop OMC/OMX itself, not how to list an external tool that integrates
with it. The Discord community (`discord.gg/PUwSMR9XNk`) would be the correct
channel to surface onmc to their user base informally.

**The good news:** onmc already ships first-class OMC and OMX adapters:
- `onmc plug omc` — installs a copy-paste adapter at `docs/integrations/omc.md`
- `onmc plug omx` — installs a copy-paste adapter at `docs/integrations/omx.md`

This means onmc users can wire the two tools together today without any registry
listing. The entry text below is prepared for when OMC/OMX adds an official
ecosystem/integrations listing.

### Entry text (for when an integrations registry opens)

For OMC skills directory (YAML frontmatter + Markdown format they use):

```yaml
---
name: onmc memory brain
description: git-portable cross-agent memory for OMC sessions — inject decisions, invariants, and failure guards at session start
triggers: ["memory", "onmc", "agent-memory", "failed approach", "why file"]
source: community
---

Integrates oh-no-my-claudecode (onmc) as a memory source for OMC sessions.

**Setup:** `onmc plug omc` in your repo — generates a copy-paste adapter at
`docs/integrations/omc.md`.

**What you get:** `onmc brief` output injected at session start, `onmc guard`
surfaces recorded dead-ends before each task, and `onmc serve --mcp` exposes
`search_memory` / `guard_task` / `get_brief` tools to OMC mid-session.

**Repo:** https://github.com/adaline-ankit/oh-no-my-claudecode
```

For a plain Markdown integrations listing:

```markdown
- [oh-no-my-claudecode (onmc)](https://github.com/adaline-ankit/oh-no-my-claudecode) — git-portable cross-agent memory brain; `onmc plug omc` wires it into OMC sessions with failure-aware recall and session-start digests.
```

### How to submit (when a registry exists)

Raise a GitHub Discussion or Discord post in the OMC/OMX community explaining
the integration. If the project adds a `PLUGINS.md` or ecosystem directory, open
a PR with the Markdown entry above.

---

## Summary Table

| List | Real entry file | Fits scope | Accepts external | Gating risk |
|---|---|---|---|---|
| punkpeye/awesome-mcp-servers | `README.md` → `🧠 Knowledge & Memory` | Strong fit | Yes, fork+PR | None stated |
| agamm/awesome-ai-sre | `README.md` → `LLM-Powered DevOps Tools` | Moderate fit | Yes, fork+PR | Needs 50+ stars |
| hesreallyhim/awesome-claude-code | `THE_RESOURCES_TABLE.csv` (bot-managed) via issue form | Strong fit | Yes, web issue only — NOT gh CLI | Maintainer discretion, selective |
| Jun-jie-Huang/awesome-LLM-AIOps | `README.md` — papers only | Does not fit (tools excluded) | No for tools | N/A |
| oh-my-claudecode / oh-my-codex | No integrations registry exists | Would fit if registry opened | Unclear / not yet | Registry doesn't exist yet |

---

## What was NOT done

- No pull requests or issues were opened against any external repository.
- No forks were created.
- No external repos were modified.
- All research was read-only (WebFetch + `gh api` read-only calls).
