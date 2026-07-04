"""Pure receipt-to-badge rendering + receipt resolution.

A "receipt" here is the plain ``dict`` parsed from a ``RunReceipt`` JSON file
(``.agent-memory/receipts/run-*.json``) — the same shape :mod:`oh_no_my_claudecode.ledger`
consumes. We read the fields we need defensively (``dict.get``) so a receipt from
an older schema version still renders a badge rather than crashing.

No I/O happens in the rendering functions; the only impure boundary is
:func:`load_receipt`, and even that never raises on a missing file — it returns
``None`` so callers can print one clean error message.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

# shields.io static-badge URL: /badge/<label>-<message>-<color>
_SHIELDS_STATIC = "https://img.shields.io/badge/{label}-{message}-{color}"

_LABEL = "onmc"
_MSG_VERIFIED = "verified"
_MSG_UNVERIFIED = "unverified"
_COLOR_VERIFIED = "brightgreen"
_COLOR_UNVERIFIED = "red"

_SHORT = 12
"""How many leading chars of a hash to show in human-facing text."""


def _is_verified(receipt: dict[str, Any]) -> bool:
    """True only when the receipt's ``verified`` flag is explicitly truthy."""
    return bool(receipt.get("verified"))


def _short(value: Any) -> str:
    """Return the first :data:`_SHORT` chars of a hash-like value, or ``"unknown"``.

    Defensive: receipts from older schema versions may omit a field entirely, in
    which case the value is ``None`` and we surface ``"unknown"`` rather than
    rendering an empty citation.
    """
    if not value:
        return "unknown"
    return str(value)[:_SHORT]


def _shields_segment(text: str) -> str:
    """Escape a string for a shields.io static-badge URL path segment.

    shields.io treats ``-`` as a field separator and ``_`` as a space, so a
    literal ``-`` must be doubled to ``--`` and a literal ``_`` doubled to ``__``.
    The result is then URL-quoted so spaces/slashes survive as a path segment.
    """
    escaped = text.replace("-", "--").replace("_", "__")
    return quote(escaped, safe="")


def load_receipt(
    receipt_or_swarm_id: str,
    *,
    unit_id: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any] | None:
    """Load a receipt dict by explicit path OR by swarm id (optionally a unit id).

    Resolution order:

    1. If ``receipt_or_swarm_id`` is a path to an existing ``.json`` file, load it
       directly.
    2. Otherwise treat it as a swarm id and read
       ``.onmc/swarm/<id>/manifest.json`` under *repo_root*. The manifest maps
       ``units[unit_id].receipt_path`` → a receipt file. When ``unit_id`` is
       given, that unit is used; otherwise the first unit that has a
       ``receipt_path`` is used.

    Returns ``None`` (never raises) when the input does not resolve to a readable
    receipt dict — a missing file, a malformed manifest, an unknown unit, or a
    unit without a receipt all yield ``None`` so the caller can print one clean
    error.

    Parameters
    ----------
    receipt_or_swarm_id:
        Either a filesystem path to a receipt JSON, or a swarm id.
    unit_id:
        Optional unit id to select within the swarm manifest. Ignored when a
        direct receipt path is given.
    repo_root:
        Repository root containing ``.onmc/swarm/``. Defaults to the current
        working directory. Only used for swarm-id resolution.
    """
    # 1. Explicit receipt path.
    as_path = Path(receipt_or_swarm_id)
    if as_path.suffix == ".json" and as_path.is_file():
        return _read_receipt_file(as_path)

    # 2. Swarm id → manifest → receipt path.
    root = repo_root if repo_root is not None else Path.cwd()
    manifest_path = root / ".onmc" / "swarm" / receipt_or_swarm_id / "manifest.json"
    manifest = _read_json(manifest_path)
    if manifest is None:
        return None
    units = manifest.get("units")
    if not isinstance(units, dict):
        return None

    receipt_path = _resolve_receipt_path(units, unit_id)
    if receipt_path is None:
        return None
    return _read_receipt_file(Path(receipt_path))


def _resolve_receipt_path(
    units: dict[str, Any], unit_id: str | None
) -> str | None:
    """Pick a ``receipt_path`` out of a manifest's ``units`` mapping.

    With ``unit_id`` given, only that unit is consulted. Without one, the first
    unit (in sorted id order, for determinism) that carries a non-empty
    ``receipt_path`` wins.
    """
    if unit_id is not None:
        unit = units.get(unit_id)
        if not isinstance(unit, dict):
            return None
        path = unit.get("receipt_path")
        return path if isinstance(path, str) and path else None

    for key in sorted(units):
        unit = units[key]
        if not isinstance(unit, dict):
            continue
        path = unit.get("receipt_path")
        if isinstance(path, str) and path:
            return path
    return None


def _read_json(path: Path) -> dict[str, Any] | None:
    """Parse a JSON object from *path*; ``None`` on any read/parse error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _read_receipt_file(path: Path) -> dict[str, Any] | None:
    """Read a receipt JSON file into a dict; ``None`` when missing/malformed."""
    return _read_json(path)


def render_markdown_badge(receipt: dict[str, Any]) -> str:
    """Render a shields.io-style Markdown badge line for *receipt*.

    Green ``onmc: verified`` when the receipt's ``verified`` flag is truthy, red
    ``onmc: unverified`` otherwise. The link-less image form is returned so it can
    be embedded anywhere Markdown is rendered (PR body, README, comment).
    """
    verified = _is_verified(receipt)
    message = _MSG_VERIFIED if verified else _MSG_UNVERIFIED
    color = _COLOR_VERIFIED if verified else _COLOR_UNVERIFIED
    url = _SHIELDS_STATIC.format(
        label=_shields_segment(_LABEL),
        message=_shields_segment(message),
        color=color,
    )
    alt = f"onmc: {message}"
    return f"![{alt}]({url})"


def endpoint_payload(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return a shields.io *endpoint* badge payload for *receipt*.

    Shape matches the shields.io endpoint schema
    (https://shields.io/badges/endpoint-badge): ``schemaVersion`` 1, a fixed
    ``label`` of ``"onmc"``, and a ``message``/``color`` pair reflecting the
    verified state. Serve this dict as JSON at a public URL and point a shields
    endpoint badge at it for a self-refreshing badge.
    """
    verified = _is_verified(receipt)
    return {
        "schemaVersion": 1,
        "label": _LABEL,
        "message": _MSG_VERIFIED if verified else _MSG_UNVERIFIED,
        "color": _COLOR_VERIFIED if verified else _COLOR_UNVERIFIED,
    }


def comment_body(receipt: dict[str, Any]) -> str:
    """Build a Markdown PR-comment body proving the work was gated + verified.

    Leads with the badge, states the verified status in plain language, and cites
    the tamper-evidence hashes (``diff_sha``, ``receipt_hash``) and the run
    ``goal``. The phrasing is tamper-evidence-forward: it says the work was
    *verified against tree <git_tree_sha>* so a reader can independently
    re-derive the hashes from the named tree.
    """
    verified = _is_verified(receipt)
    badge = render_markdown_badge(receipt)
    goal = str(receipt.get("goal") or "(no goal recorded)")
    tree_short = _short(receipt.get("git_tree_sha"))
    diff_short = _short(receipt.get("diff_sha"))
    hash_short = _short(receipt.get("receipt_hash"))

    status_line = (
        "This change was gated by onmc and **verified** — the diff was checked "
        "against the recorded work before landing."
        if verified
        else "onmc recorded this change but it is **not verified** — the "
        "verification gate did not pass. Treat it as unproven."
    )

    lines = [
        badge,
        "",
        "### onmc — No-Slop proof of work",
        "",
        status_line,
        "",
        f"- **Goal:** {goal}",
        f"- **Verified:** {'yes' if verified else 'no'}",
        f"- **Verified against tree** `{tree_short}`",
        f"- **Diff hash** `{diff_short}`",
        f"- **Receipt hash** `{hash_short}` (tamper-evident)",
        "",
        "_Hashes are reproducible from the named git tree; a re-run that changed "
        "the diff would change the receipt hash._",
    ]
    return "\n".join(lines)
