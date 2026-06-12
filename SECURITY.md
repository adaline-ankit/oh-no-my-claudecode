# Security Policy

## Supported Versions

ONMC is pre-1.0. Security fixes target the latest released version and `main`.

## Reporting a Vulnerability

Do not open a public issue for vulnerabilities.

Use GitHub private vulnerability reporting:

https://github.com/adaline-ankit/oh-no-my-claudecode/security/advisories/new

Include:

- affected ONMC version or commit
- operating system and Python version
- reproduction steps
- whether Claude Code hooks, MCP, sync export, or transcript mining are involved
- sanitized examples of generated memory or agent context

## Security Boundaries

ONMC stores local repo memory and can read git history, docs, selected source files,
Claude Code transcripts, and exported `.agent-memory` data. Treat all of those inputs
as untrusted when they come from forks, issue attachments, or external repositories.

Core expectations:

- never commit API keys, Claude credentials, OpenAI keys, private prompts, or customer code
- keep `.onmc/` local and gitignored because it contains local SQLite state and logs
- review `.agent-memory/` before committing because it is designed to be portable
- prefer least-privilege GitHub tokens for CI and release automation
- route dependency, hook, MCP, storage, and LLM-provider changes through maintainer review

## Agent-Specific Risks

ONMC exists to feed useful context to coding agents, so prompt-injection and stale-memory
risks matter. Security reports are especially useful when they show that ONMC:

- includes secrets or private data in generated agent context
- lets untrusted repo content override maintainer guidance
- installs hooks or MCP configuration outside the intended repo/user boundary
- restores `.agent-memory` records without clear provenance
- causes Claude Code, Codex, or another agent to receive misleading instructions
