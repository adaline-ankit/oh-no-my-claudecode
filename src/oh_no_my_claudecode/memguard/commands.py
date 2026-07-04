"""CLI surface for the ``memguard`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc memguard`` ships with **zero
edits** to ``cli.py`` or any other shared hub.

``onmc memguard scan`` reads the onmc memory store and flags entries containing:
- Prompt-injection patterns
- Credential-exfiltration attempts
- SSH/backdoor one-liners
- Invisible/dangerous Unicode (zero-width, bidi overrides, tag chars)

Pure stdlib — no network calls, no new dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.memguard.scanner import Report, scan_memories

if TYPE_CHECKING:
    from oh_no_my_claudecode.storage import SQLiteStorage

memguard_app = typer.Typer(
    help="Memory-integrity firewall: scan memory entries for adversarial content.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Register the ``onmc memguard`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(memguard_app, name="memguard")


def _load_storage(repo_root: Path) -> SQLiteStorage:
    """Load the SQLite storage for *repo_root*.

    Raises :class:`typer.Exit` with code 1 when onmc is not initialised.
    """
    from oh_no_my_claudecode.config import config_exists, database_path, load_config
    from oh_no_my_claudecode.storage import SQLiteStorage

    if not config_exists(repo_root):
        typer.echo("error: onmc is not initialized in this repo. Run `onmc init` first.", err=True)
        raise typer.Exit(code=1)

    config = load_config(repo_root)
    storage = SQLiteStorage(database_path(config, repo_root))
    storage.initialize()
    return storage


def _render_report_plain(report: Report) -> None:
    """Render *report* as human-readable plain text."""
    status = "PASS" if report.passed else "FAIL"
    typer.echo(f"\n  onmc memguard — memory integrity scan  [{status}]\n")
    typer.echo(f"  entries scanned : {report.total_scanned}")
    typer.echo(f"  entries flagged : {report.total_flagged}")

    counts = report.counts_by_severity
    severity_display = "  severity counts : " + "  ".join(
        f"{s}={counts[s]}" for s in ("critical", "high", "medium", "low") if counts[s]
    )
    if any(counts[s] for s in ("critical", "high", "medium", "low")):
        typer.echo(severity_display)

    if report.passed:
        typer.echo("\n  All memory entries are clean. No threats detected.\n")
        return

    typer.echo("")
    for entry in report.entries:
        if not entry.findings:
            continue
        typer.echo(f"  ⚠  {entry.entry_id[:16]}  {entry.entry_title[:60]}")
        for finding in entry.findings:
            snippet = repr(finding.match[:60]) if finding.match else ""
            typer.echo(f"     [{finding.severity.upper():8}] {finding.rule_id}  {finding.title}")
            if snippet:
                typer.echo(f"              match: {snippet}")
        typer.echo("")


@memguard_app.command("scan")
def scan_command(
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                'Emit a JSON envelope {"kind": "memguard", "report": {...}} '
                "for pipeline composition."
            ),
        ),
    ] = False,
    include_clean: Annotated[
        bool,
        typer.Option(
            "--include-clean",
            help="Include clean (no-finding) entries in the output.",
        ),
    ] = False,
    fail_on: Annotated[
        str | None,
        typer.Option(
            "--fail-on",
            help="Exit 1 when a finding exists at or above SEVERITY (critical/high/medium/low).",
            metavar="SEVERITY",
        ),
    ] = None,
) -> None:
    """Scan the onmc memory store for adversarial content.

    Reads every memory entry and checks for:

    \\b
    - Prompt-injection / system-prompt override phrases (MG-INJ-*)
    - Credential exfiltration attempts (MG-EXF-*)
    - SSH authorized_keys writes and reverse-shell one-liners (MG-SSH-*)
    - Invisible/dangerous Unicode: zero-width chars, bidi overrides,
      tag chars (MG-UNI-*)

    Pure stdlib — deterministic, offline, no network calls.

    Examples:

        onmc memguard scan               # human-readable report

        onmc memguard scan --json        # JSON envelope for pipelines

        onmc memguard scan --fail-on high  # exit 1 when high+ findings exist
    """
    try:
        repo_root = discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("error: no git repository found from the current directory.", err=True)
        raise typer.Exit(code=1) from None

    storage = _load_storage(repo_root)
    memories = storage.list_memories()

    report = scan_memories(memories, include_clean=include_clean)

    if as_json:
        payload = _report_to_dict(report)
        typer.echo(json.dumps({"kind": "memguard", "report": payload}, indent=2, sort_keys=True))
    else:
        _render_report_plain(report)

    # --fail-on exit-code handling
    if fail_on is not None:
        _severity_order = ["critical", "high", "medium", "low", "info"]
        if fail_on not in _severity_order:
            typer.echo(
                f"error: --fail-on value must be one of {_severity_order[:-1]}, got '{fail_on}'",
                err=True,
            )
            raise typer.Exit(code=2)
        threshold_idx = _severity_order.index(fail_on)
        counts = report.counts_by_severity
        triggered = any(
            counts.get(s, 0) > 0
            for s in _severity_order
            if _severity_order.index(s) <= threshold_idx
        )
        if triggered:
            raise typer.Exit(code=1)

    if not report.passed and not as_json and fail_on is None:
        # Surfaced as a non-zero exit even without --fail-on for discoverability.
        raise typer.Exit(code=1)


def _report_to_dict(report: Report) -> dict[str, object]:
    """Serialise a :class:`~oh_no_my_claudecode.memguard.scanner.Report` to a plain dict."""
    return {
        "passed": report.passed,
        "total_scanned": report.total_scanned,
        "total_flagged": report.total_flagged,
        "counts_by_severity": report.counts_by_severity,
        "entries": [
            {
                "entry_id": e.entry_id,
                "entry_title": e.entry_title,
                "passed": e.passed,
                "findings": [
                    {
                        "rule_id": f.rule_id,
                        "severity": f.severity,
                        "title": f.title,
                        "detail": f.detail,
                        "match": f.match,
                    }
                    for f in e.findings
                ],
            }
            for e in report.entries
        ],
    }
