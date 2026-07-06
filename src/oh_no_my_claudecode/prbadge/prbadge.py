"""Pure badge-building logic for ``onmc prbadge``.

Reuses :mod:`oh_no_my_claudecode.ledger.accounting` to aggregate run receipts
(the same ``.agent-memory/receipts/run-*.json`` corpus ``onmc ledger`` reads)
into a :class:`LedgerSummary`, then renders a compact, shareable Markdown
badge from it. No new schema, no new reader — this module only formats
numbers the ledger already computed honestly.

Everything here is pure: given a :class:`~oh_no_my_claudecode.ledger.accounting.LedgerSummary`
(or an injected receipt list), the output is deterministic. The only impure
boundary anywhere in the feature is the ``gh pr comment`` shell-out, which
lives in :mod:`oh_no_my_claudecode.prbadge.commands` — never here.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from oh_no_my_claudecode.ledger.accounting import LedgerSummary, summarize_receipts

__all__ = ["BadgeContent", "build_badge", "render_markdown"]

# shields.io static-badge URL: /badge/<label>-<message>-<color> — same pattern
# used by oh_no_my_claudecode.badge and oh_no_my_claudecode.scorecard.
_SHIELDS_STATIC = "https://img.shields.io/badge/{label}-{message}-{color}"

_LABEL = "onmc"
_COLOR_ZERO = "lightgrey"
_COLOR_LOW = "red"
_COLOR_MID = "yellow"
_COLOR_HIGH = "brightgreen"


@dataclass(frozen=True)
class BadgeContent:
    """The structured badge data — everything :func:`render_markdown` needs.

    Attributes
    ----------
    run_count:
        Total receipts considered.
    verified_count:
        Receipts with ``verified=True``.
    verified_pct:
        ``round(100 * verified_count / run_count, 1)``, or ``None`` when
        ``run_count == 0`` (honest zero-state — never a fabricated 0%).
    onmc_version:
        The onmc package version string that built this PR ("0+unknown" when
        the package metadata is unavailable).
    shields_url:
        The shields.io static-badge image URL summarising verified-rate.
    note:
        The ledger's own honest caveat (e.g. "no receipts found") when
        applicable, else an empty string.
    """

    run_count: int
    verified_count: int
    verified_pct: float | None
    onmc_version: str
    shields_url: str
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of the badge data."""
        return {
            "run_count": self.run_count,
            "verified_count": self.verified_count,
            "verified_pct": self.verified_pct,
            "onmc_version": self.onmc_version,
            "shields_url": self.shields_url,
            "note": self.note,
        }


def _shields_segment(text: str) -> str:
    """Escape a string for a shields.io static-badge URL path segment.

    shields.io treats ``-`` as a field separator and ``_`` as a space, so a
    literal ``-`` is doubled to ``--`` and ``_`` to ``__``, then URL-quoted.
    """
    escaped = text.replace("-", "--").replace("_", "__")
    return quote(escaped, safe="")


def _color_for(verified_pct: float | None) -> str:
    """Map a verified percentage to a shields.io badge colour.

    ``None`` (no receipts at all) renders neutral grey rather than red, since
    "no data" and "0% verified" are honestly different states.
    """
    if verified_pct is None:
        return _COLOR_ZERO
    if verified_pct >= 80.0:
        return _COLOR_HIGH
    if verified_pct >= 40.0:
        return _COLOR_MID
    return _COLOR_LOW


def _shields_url(run_count: int, verified_pct: float | None) -> str:
    """Build the shields.io static-badge URL for the given stats."""
    message = "no data" if run_count == 0 else f"{verified_pct:g}pct verified"
    color = _color_for(verified_pct)
    return _SHIELDS_STATIC.format(
        label=_shields_segment(_LABEL),
        message=_shields_segment(message),
        color=color,
    )


def build_badge(summary: LedgerSummary, *, onmc_version: str) -> BadgeContent:
    """Build a :class:`BadgeContent` from an already-computed :class:`LedgerSummary`.

    Pure: no I/O. Callers that want to build from raw receipts should call
    :func:`build_badge_from_receipts` instead.

    Parameters
    ----------
    summary:
        A :class:`~oh_no_my_claudecode.ledger.accounting.LedgerSummary`
        (e.g. from :func:`~oh_no_my_claudecode.ledger.accounting.summarize_receipts`).
    onmc_version:
        The onmc package version string to cite ("built with onmc vY").
    """
    run_count = summary.run_count
    verified_pct = (
        round(100.0 * summary.success_count / run_count, 1) if run_count > 0 else None
    )
    return BadgeContent(
        run_count=run_count,
        verified_count=summary.success_count,
        verified_pct=verified_pct,
        onmc_version=onmc_version,
        shields_url=_shields_url(run_count, verified_pct),
        note=summary.note,
    )


def build_badge_from_receipts(
    receipts: list[dict[str, object]], *, onmc_version: str
) -> BadgeContent:
    """Convenience wrapper: aggregate *receipts* then build the badge.

    Still pure — *receipts* is an injected list, never read from disk here.
    """
    summary = summarize_receipts(receipts, scope="project")
    return build_badge(summary, onmc_version=onmc_version)


def render_markdown(content: BadgeContent) -> str:
    """Render *content* as a compact, shareable Markdown PR-comment body.

    Deterministic: the same :class:`BadgeContent` always yields the same
    Markdown. Zero-state (``run_count == 0``) renders an honest "no verified
    receipts yet" line instead of a fabricated percentage.
    """
    alt = "onmc: no data" if content.run_count == 0 else f"onmc: {content.verified_pct:g}% verified"
    badge_line = f"![{alt}]({content.shields_url})"

    if content.run_count == 0:
        headline = "No onmc-verified receipts recorded yet."
    else:
        headline = (
            f"**{content.run_count}** onmc loop"
            f"{'s' if content.run_count != 1 else ''} recorded — "
            f"**{content.verified_pct:g}%** verified "
            f"({content.verified_count}/{content.run_count})."
        )

    onmc_link = "https://github.com/adaline-ankit/oh-no-my-claudecode"
    lines = [
        badge_line,
        "",
        "### ✓ onmc-verified — proof of work",
        "",
        headline,
        "",
        f"_Built with [onmc]({onmc_link}) v{content.onmc_version}._",
    ]
    if content.note and content.run_count == 0:
        lines.append("")
        lines.append(f"> {content.note}")
    return "\n".join(lines)
