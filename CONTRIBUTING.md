# Contributing

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Local Checks

```bash
ruff check .
mypy src
pytest --cov=oh_no_my_claudecode --cov-report=term-missing --cov-fail-under=80
python scripts/generate-cli-reference.py --check
python -m build
python -m twine check dist/*
```

Run the smallest relevant test while developing, then run the full gate before asking
for review.

## Scope Guidance

This project is intentionally narrow. Good contributions should keep the tool:

- local-first
- provenance-driven
- useful without mandatory model access
- honest about heuristic confidence

Avoid turning the project into a hosted platform, a generic multi-agent wrapper, or a prompt-pack repository.

Good issue areas:

- Claude Code hook reliability
- MCP resources and tools
- Codex and cloud-agent restore flows
- portable `.agent-memory` workflows
- memory provenance, ranking, and debugging
- setup, doctor, and health checks

Open a design issue before adding:

- telemetry
- a hosted service
- new long-running daemons
- a new storage backend
- a new LLM provider dependency path
- broad prompt-pack or multi-agent orchestration features

## Adding a command (auto-discovery)

New CLI commands **self-register** — you do **not** edit `cli.py` (or any other
shared hub). This avoids merge collisions when several feature PRs land in
parallel.

To add a command for a feature `myfeat`:

1. Create `src/oh_no_my_claudecode/myfeat/commands.py` exposing a top-level
   `register(app)`:

   ```python
   from __future__ import annotations

   import typer

   def register(app: typer.Typer) -> None:
       myfeat_app = typer.Typer(help="...", no_args_is_help=True)

       @myfeat_app.command("run")
       def run() -> None:
           ...

       app.add_typer(myfeat_app, name="myfeat")
       # ...or register a single command directly:
       # @app.command("myfeat")
       # def myfeat_cmd() -> None: ...
   ```

2. Do your **own** rendering inline in that module (e.g. `typer.echo(...)` or a
   local Rich console). Do not add to the shared rendering hub.

3. That's it. `oh_no_my_claudecode.command_registry.register_feature_commands`,
   invoked once near the end of `cli.py`, discovers every `<feat>.commands`
   module and calls its `register(app)` at CLI build time. Discovery is
   deterministic (sorted), idempotent, and robust — a broken or optional feature
   is skipped (logged at debug) and never crashes the CLI.

4. The CLI reference picks it up for free. `scripts/generate-cli-reference.py`
   introspects the fully-built `app` (after auto-discovery) and enumerates every
   command + nested subcommand automatically — there is **no** hardcoded command
   list to edit. Just regenerate the doc: `python scripts/generate-cli-reference.py`.

**Do not touch** these shared files when adding a command:
`cli.py`, `core/service.py`, `rendering/console.py`, `scripts/generate-cli-reference.py`.
None of them need a per-command edit anymore — the generator auto-discovers.

See `src/oh_no_my_claudecode/registrydemo/commands.py` for a complete, working
example (the `onmc registry-demo` command).

## Pull Requests

- keep changes focused
- add or update tests for behavior changes
- update docs when CLI behavior or memory semantics change
- prefer deterministic heuristics over opaque inference for core paths
- explain whether Claude Code, Codex, MCP, sync, or `.agent-memory` behavior changed
- do not commit `.onmc/`, secrets, private prompts, or proprietary source snippets
- expect maintainer review through `CODEOWNERS`
- regenerate `docs/cli-reference.md` when CLI help changes

Agent-generated PRs are welcome when they are reproducible. Include the exact commands
used for validation and keep the diff scoped to the issue.

## Labels

Maintainers use labels to route work:

- `needs-triage`: new issue or PR needs maintainer classification
- `good first issue`: narrow, documented, and safe for new contributors
- `help wanted`: maintainer wants outside implementation help
- `agent-integration`: Claude Code, Codex, Cursor, MCP, or cloud-agent path
- `memory-model`: extraction, provenance, ranking, or sync semantics
- `security`: vulnerability, secret-handling, or trust-boundary concern
- `ci`: GitHub Actions, release, packaging, or quality gate work

## Release Notes

Release automation is scaffolded through GitHub Actions trusted publishing, but repository and PyPI configuration still need to be wired in the target GitHub project.
