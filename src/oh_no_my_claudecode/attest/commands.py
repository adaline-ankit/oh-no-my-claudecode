"""CLI surface for the ``attest`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. No shared hub (``cli.py``, ``rendering/``, service
layer) is touched.

Receipt resolution reuses :func:`oh_no_my_claudecode.badge.badge.load_receipt`
(path or swarm-id + ``--unit``) so ``attest sign`` accepts exactly the same
inputs as ``onmc badge``. The reputation scan reads the receipts directory
directly, mirroring the ledger's loader, and folds it through the pure
:func:`oh_no_my_claudecode.attest.attest.build_reputation`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.attest.attest import (
    Attestation,
    ReputationSummary,
    build_attestation,
    build_reputation,
    verify_attestation,
)
from oh_no_my_claudecode.badge.badge import load_receipt


def _repo_root() -> Path:
    """Best-effort repo root; falls back to cwd when discovery is unavailable.

    ``attest`` never *requires* an initialised onmc repo (it operates on receipt
    files that may live anywhere), so a discovery failure is not fatal — we
    resolve relative receipt-directory scans against the current directory.
    """
    try:
        from oh_no_my_claudecode.core.repo import (  # noqa: PLC0415 - optional, lazy
            discover_repo_root,
        )

        return discover_repo_root(Path.cwd())
    except Exception:  # noqa: BLE001 - discovery is best-effort; cwd is a fine fallback
        return Path.cwd()


def _scan_receipts(repo_root: Path) -> list[dict[str, Any]]:
    """Load every ``run-*.json`` receipt under ``.agent-memory/receipts/``.

    Mirrors the ledger loader's directory + filename convention (``run-*.json``)
    so the reputation scan sees exactly the receipts the ledger accounts for.
    Malformed or unreadable files are skipped silently; a missing directory
    yields an empty list.
    """
    receipts_dir = repo_root / ".agent-memory" / "receipts"
    out: list[dict[str, Any]] = []
    if not (receipts_dir.exists() and receipts_dir.is_dir()):
        return out
    for entry in sorted(receipts_dir.iterdir()):
        if entry.suffix != ".json" or not entry.name.startswith("run-"):
            continue
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def _render_attestation(att: Attestation) -> None:
    """Emit a human-readable rendering of *att* (plain text, no Rich needed)."""
    claim = att.claim
    verified = "yes" if claim.get("verified") else "no"
    proof = "signed (HMAC-SHA256)" if att.signed else "unsigned digest (SHA256)"
    lines = [
        "",
        "  onmc attest — proof-of-work attestation",
        f"  subject:     {att.subject}",
        f"  goal:        {claim.get('goal') or '(no goal recorded)'}",
        f"  verified:    {verified}",
        f"  git tree:    {claim.get('git_tree_sha') or 'unknown'}",
        f"  diff sha:    {claim.get('diff_sha') or 'unknown'}",
        f"  receipt sha: {claim.get('receipt_hash') or 'unknown'}",
        f"  ts:          {claim.get('ts') or 'unknown'}",
        f"  proof:       {proof}",
        f"  signature:   {att.signature}",
        "",
    ]
    if not att.signed:
        lines.append(
            "  Note: no secret present — this is a tamper-evidence digest, not "
            "an authenticity proof. Set ONMC_ATTEST_SECRET or pass --secret to sign."
        )
        lines.append("")
    typer.echo("\n".join(lines))


def _render_reputation(summary: ReputationSummary) -> None:
    """Emit a human-readable rendering of a :class:`ReputationSummary`."""
    if summary.total == 0:
        typer.echo(
            "\n  onmc attest — no receipts found under .agent-memory/receipts/.\n"
            "  Run `onmc loop` or `onmc swarm` to accumulate a track record.\n"
        )
        return
    subjects = ", ".join(summary.subjects) if summary.subjects else "(none)"
    rate_pct = f"{summary.verified_rate * 100:.1f}%"
    lines = [
        "",
        "  onmc attest — agent reputation (track record)",
        f"  runs:          {summary.total}",
        f"  attested:      {summary.attested}  (carry tamper-evidence hashes)",
        f"  verified:      {summary.verified}  ({rate_pct} verified-rate)",
        f"  distinct goals:{summary.distinct_goals:>4}",
        f"  subjects:      {subjects}",
        f"  first run:     {summary.first_ts or 'unknown'}",
        f"  last run:      {summary.last_ts or 'unknown'}",
        "",
    ]
    typer.echo("\n".join(lines))


def register(app: typer.Typer) -> None:
    """Register the ``attest`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    attest_app = typer.Typer(
        no_args_is_help=True,
        help="Verifiable, portable proof-of-work — turn a receipt into a signed attestation.",
    )

    @attest_app.command("sign")
    def sign_command(
        receipt_or_swarm_id: Annotated[
            str,
            typer.Argument(
                help="Path to a receipt JSON, or a swarm id (resolved via its manifest)."
            ),
        ],
        unit_id: Annotated[
            str | None,
            typer.Option("--unit", help="Unit id to select when a swarm id is given."),
        ] = None,
        secret: Annotated[
            str | None,
            typer.Option(
                "--secret",
                help="Shared secret for HMAC signing (else ONMC_ATTEST_SECRET, else unsigned).",
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the attestation as JSON."),
        ] = False,
    ) -> None:
        """Build a signed, portable attestation from an onmc receipt.

        Distils the receipt into a minimal verifiable claim (subject, goal,
        tamper-evidence hashes, verified flag, timestamp) and signs it. With a
        secret (``--secret`` or ``ONMC_ATTEST_SECRET``) the signature is an
        HMAC-SHA256; without one it is a SHA256 integrity digest, clearly marked
        unsigned. ``--json`` emits the attestation for a verifier or registry.
        """
        receipt = load_receipt(receipt_or_swarm_id, unit_id=unit_id)
        if receipt is None:
            typer.echo(
                f"No readable receipt for {receipt_or_swarm_id!r}"
                + (f" (unit {unit_id!r})" if unit_id else "")
                + ". Pass a receipt JSON path or a swarm id with a manifest.",
                err=True,
            )
            raise typer.Exit(code=1)

        attestation = build_attestation(receipt, secret=secret)
        if as_json:
            typer.echo(json.dumps(attestation.to_dict()))
            return
        _render_attestation(attestation)

    @attest_app.command("verify")
    def verify_command(
        file: Annotated[
            str,
            typer.Argument(help="Path to an attestation JSON produced by `attest sign --json`."),
        ],
        secret: Annotated[
            str | None,
            typer.Option(
                "--secret",
                help="Shared secret for HMAC verification (else ONMC_ATTEST_SECRET).",
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the verify result as JSON."),
        ] = False,
    ) -> None:
        """Verify an attestation file; exit 0 when valid, 1 when not.

        Recomputes the signature over the embedded claim and compares it in
        constant time. A signed attestation only passes with the correct secret;
        an unsigned one passes on its integrity digest alone.
        """
        path = Path(file)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            typer.echo(f"Cannot read attestation {file!r}: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        if not isinstance(raw, dict):
            typer.echo(f"Attestation {file!r} is not a JSON object.", err=True)
            raise typer.Exit(code=1)

        attestation = Attestation.from_dict(raw)
        ok = verify_attestation(attestation, secret)

        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "valid": ok,
                        "subject": attestation.subject,
                        "signed": attestation.signed,
                        "alg": attestation.alg,
                    }
                )
            )
        else:
            verdict = "PASS" if ok else "FAIL"
            proof = "signed" if attestation.signed else "unsigned digest"
            typer.echo(
                f"{verdict} — attestation for {attestation.subject!r} "
                f"({proof}) {'verified' if ok else 'did NOT verify'}."
            )
        if not ok:
            raise typer.Exit(code=1)

    @attest_app.command("reputation")
    def reputation_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the reputation summary as JSON."),
        ] = False,
    ) -> None:
        """Summarise this repo's agent track record from all receipts.

        Scans ``.agent-memory/receipts/`` and folds every run into a portable
        reputation summary: total runs, how many are attestable, verified-rate,
        distinct goals, and the time span — the shape an ERC-8004 reputation
        registry would consume.
        """
        summary = build_reputation(_scan_receipts(_repo_root()))
        if as_json:
            typer.echo(json.dumps(summary.to_dict()))
            return
        _render_reputation(summary)

    app.add_typer(attest_app, name="attest")
