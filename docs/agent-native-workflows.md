# Agent-Native Workflows

ONMC is designed to make coding agents start with useful repo memory instead of a
blank context window. This document defines the supported agent surfaces and the
guardrails contributors should preserve.

## Supported Surfaces

### Claude Code

Claude Code should receive repo guidance through:

- `CLAUDE.md` for source-controlled project instructions
- `onmc hooks install` for compaction/session context
- `onmc serve --mcp` for mid-session memory lookup
- `onmc mine` for extracting useful memories from prior Claude Code transcripts

Contributors changing this path should test hook installation, hook status, generated
payload shape, and MCP resource/tool behavior.

### Codex and Cloud Agents

Codex and ephemeral cloud agents should receive repo context through:

- `AGENTS.md` for source-controlled project instructions
- `onmc sync --restore` for portable `.agent-memory/`
- `onmc brief --task "..."` for task-scoped context

Cloud-agent flows must not assume access to the developer's local `.onmc/` database.
They should work from committed docs plus `.agent-memory/` exports.

### MCP Clients

MCP clients should use ONMC resources and tools for lookup, not direct SQLite access.
The MCP boundary lets ONMC preserve provenance, filtering, and future schema changes.

### Cursor and Rule-Based Agents

Rule-file integrations should consume `onmc brief` output or committed memory exports.
Avoid adding provider-specific prompt packs unless they are thin adapters over ONMC's
structured memory.

## Guardrails

Agent-facing changes must preserve these properties:

- local-first: no hosted service is required for the core workflow
- provenance-aware: memory records retain source references and confidence
- reviewable: committed memory exports are readable and diffable
- bounded: repo instructions cannot silently override maintainer policy
- portable: fresh machines can restore from committed exports
- safe-by-default: secrets and local databases stay out of git

## Contribution Checklist

Use this checklist when changing hooks, MCP, sync, prompts, or generated files:

- update tests for the affected agent surface
- run `onmc doctor` or the closest test fixture when setup behavior changes
- document new commands or payload expectations
- avoid adding new long-running background processes
- explain how the change behaves in a fresh clone or cloud container
