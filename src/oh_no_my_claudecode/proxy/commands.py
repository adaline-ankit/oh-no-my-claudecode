"""CLI surface for the ``proxy`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc proxy`` ships with **zero
edits** to ``cli.py`` or any other shared hub.

``onmc proxy serve`` starts an OpenAI-compatible HTTP server that forwards
``POST /v1/chat/completions`` to onmc's configured LLM provider and returns an
OpenAI-shaped response.  External tools (Codex / Aider / Cline / Continue) can
point at ``http://localhost:<port>/v1`` to use whatever backend onmc is
configured with — no separate API key needed by the tool if the provider is
already set up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

proxy_app = typer.Typer(
    help="OpenAI-compatible local proxy for onmc's configured LLM provider.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Register the ``onmc proxy`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(proxy_app, name="proxy")


@proxy_app.command("serve")
def proxy_serve_command(
    port: Annotated[
        int,
        typer.Option(
            "--port",
            help="TCP port to listen on.",
            show_default=True,
        ),
    ] = 8760,
    host: Annotated[
        str,
        typer.Option(
            "--host",
            help="Bind address (use 0.0.0.0 to expose to the network).",
            show_default=True,
        ),
    ] = "127.0.0.1",
) -> None:
    """Start an OpenAI-compatible proxy backed by onmc's configured LLM provider.

    The server exposes two endpoints:

    \\b
    POST /v1/chat/completions   ← OpenAI ChatCompletions (non-streaming)
    GET  /v1/models             ← Returns the configured model as a list entry

    External tools (Codex, Aider, Cline, Continue, …) can be pointed at
    ``http://<host>:<port>/v1`` and will use whatever LLM backend onmc is
    configured with, without needing their own API keys for that backend.

    Examples:

        onmc proxy serve

        onmc proxy serve --port 9000

        onmc proxy serve --host 0.0.0.0 --port 8760
    """
    from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
    from oh_no_my_claudecode.core.service import OnmcService
    from oh_no_my_claudecode.llm import LLMConfigurationError, provider_from_settings
    from oh_no_my_claudecode.proxy.server import ProxyServer

    try:
        repo_root = discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        repo_root = Path.cwd()

    # Load settings — non-fatal if repo has no config; fall back to defaults.
    service = OnmcService(repo_root)
    try:
        _root, config, _storage = service._load_context()
        settings = config.llm
    except Exception:  # noqa: BLE001 - graceful degradation if no onmc config
        from oh_no_my_claudecode.models.llm import LLMSettings

        settings = LLMSettings()

    try:
        provider = provider_from_settings(settings)
    except LLMConfigurationError as exc:
        typer.echo(
            f"error: LLM provider is not configured — {exc}\n"
            "Run `onmc setup` to configure a provider before starting the proxy.",
            err=True,
        )
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"onmc proxy: listening on http://{host}:{port}/v1  "
        f"(provider={provider.settings.provider}, model={provider.settings.model})",
        err=True,
    )
    typer.echo("Press Ctrl-C to stop.", err=True)

    with ProxyServer(provider, host=host, port=port) as srv:
        typer.echo(f"onmc proxy: ready on http://{host}:{srv.port}/v1", err=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            typer.echo("\nonmc proxy: shutting down.", err=True)
