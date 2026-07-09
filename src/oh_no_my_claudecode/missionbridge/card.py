"""Trust-card builder + channel renderers for the mission bridge.

The card is the "wow" surface a user approves a swarm from on their phone: a
channel-agnostic :class:`~oh_no_my_claudecode.missionbridge.models.MissionCard`
built from the swarm manifest + tamper-evident receipts, plus pure renderers
for Slack Block Kit, Telegram markdown, and a plain-text fallback.

Design rules:

- **Honest.** A unit is only ``verified`` if the manifest marks it verified AND
  a receipt exists on disk; everything else is ``held`` and clearly labelled
  "held, not shipped".  Cost is summed from receipts only — never fabricated;
  it is ``None`` (rendered "n/a") when receipts carry no cost.
- **Reuse.** Unit/receipt loading is delegated to the ``missioncontrol``
  dashboard reader (:func:`~oh_no_my_claudecode.missioncontrol.dashboard.build_dashboard`)
  and its receipt helpers — this module never re-parses the manifest itself.
- **Pure.** :func:`build_card` only reads files; the renderers touch no I/O.
- **Deterministic.** Units keep the dashboard's sorted order and the same
  inputs always yield the same card and rendering.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from oh_no_my_claudecode.missionbridge.models import MissionCard, UnitLine
from oh_no_my_claudecode.missioncontrol.dashboard import (
    _read_json,
    _resolve_receipt_path,
    build_dashboard,
)
from oh_no_my_claudecode.swarm.orchestrator import _swarm_dir

if TYPE_CHECKING:
    from oh_no_my_claudecode.missioncontrol.dashboard import UnitStatus

# Action-id / callback-data namespace shared by every channel so an inbound
# webhook can route a Slack button and a Telegram tap through one parser.
ACTION_APPROVE_ALL = "mission:approve_all"
ACTION_ABORT = "mission:abort"
_ACTION_APPROVE_PREFIX = "mission:approve:"
_ACTION_SHOW_DIFF_PREFIX = "mission:show_diff:"

_VERIFIED_GLYPH = "✅"
_HELD_GLYPH = "⛔"


def _approve_action(unit_id: str) -> str:
    """Return the per-unit approve action id (e.g. ``mission:approve:unit-0001``)."""
    return f"{_ACTION_APPROVE_PREFIX}{unit_id}"


def _show_diff_action(unit_id: str) -> str:
    """Return the per-unit show-diff action id."""
    return f"{_ACTION_SHOW_DIFF_PREFIX}{unit_id}"


def _cost_from_receipt(receipt: dict[str, Any] | None) -> float | None:
    """Extract an honest ``cost_usd`` from a receipt, or ``None`` if absent."""
    if receipt is None:
        return None
    raw = receipt.get("cost_usd")
    if raw is None:
        return None
    if isinstance(raw, bool):  # bool is an int subclass — never a cost.
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _unit_line(unit: UnitStatus, swarm_dir: Path) -> tuple[UnitLine, float | None]:
    """Map one dashboard :class:`UnitStatus` to a :class:`UnitLine`.

    Returns the line plus the unit's receipt cost (``None`` when absent) so the
    caller can sum totals honestly.
    """
    resolved = _resolve_receipt_path(swarm_dir, unit.receipt_path)
    receipt: dict[str, Any] | None = None
    if resolved is not None and resolved.exists():
        receipt = _read_json(resolved)

    # Verified success = manifest says verified AND a receipt backs it up.
    verified = unit.verified is True and unit.has_receipt
    held = not verified

    cost = _cost_from_receipt(receipt)
    receipt_hash = None
    pr_url = None
    if receipt is not None:
        rh = receipt.get("receipt_hash")
        receipt_hash = str(rh) if rh else None
        pu = receipt.get("pr_url")
        pr_url = str(pu) if pu else None

    detail = "" if verified else "held, not shipped"
    if held and unit.error:
        detail = f"held, not shipped ({unit.error})"

    line = UnitLine(
        unit_id=unit.unit_id,
        goal=unit.goal,
        status=unit.state,
        verified=verified,
        held=held,
        cost_usd=cost,
        diff_sha=unit.diff_sha,
        receipt_hash=receipt_hash,
        pr_url=pr_url,
        detail=detail,
    )
    return line, cost


def build_card(repo_root: Path | str, swarm_id: str, *, goal: str = "") -> MissionCard:
    """Build a :class:`MissionCard` for one swarm from its manifest + receipts.

    Parameters
    ----------
    repo_root:
        Repository root containing ``.onmc/swarm/<id>`` and
        ``.agent-memory/receipts/``.
    swarm_id:
        The swarm to report on.
    goal:
        Optional mission goal for the card header.

    Returns
    -------
    MissionCard
        An empty card (no units, ``total_cost_usd=None``) when the swarm has no
        readable manifest — never raises for missing state.
    """
    root = Path(repo_root)
    state_dir = root / ".onmc" / "swarm"
    model = build_dashboard(state_dir, swarm_id)

    if not model.exists:
        return MissionCard(
            mission_id=swarm_id,
            goal=goal,
            units=[],
            total_cost_usd=None,
            generated_note="no swarm state found",
        )

    swarm_dir = _swarm_dir(root, swarm_id)
    lines: list[UnitLine] = []
    costs: list[float] = []
    for unit in model.units:
        line, cost = _unit_line(unit, swarm_dir)
        lines.append(line)
        if cost is not None:
            costs.append(cost)

    total_cost = sum(costs) if costs else None
    return MissionCard(
        mission_id=model.swarm_id,
        goal=goal,
        units=lines,
        total_cost_usd=total_cost,
    )


# ---------------------------------------------------------------------------
# Renderers (pure — no I/O, no network)
# ---------------------------------------------------------------------------


def _fmt_cost(cost: float | None) -> str:
    """Human-honest cost string; ``"n/a"`` when unknown."""
    return f"${cost:.2f}" if cost is not None else "n/a"


def _unit_summary(unit: UnitLine) -> str:
    """One-line human summary of a unit's trust signals."""
    glyph = _VERIFIED_GLYPH if unit.verified else _HELD_GLYPH
    label = "VERIFIED" if unit.verified else "HELD"
    bits = [f"{glyph} {label}", unit.unit_id]
    if unit.goal:
        bits.append(unit.goal)
    tail = [f"cost {_fmt_cost(unit.cost_usd)}"]
    if unit.diff_sha:
        tail.append(f"diff {unit.diff_sha[:12]}")
    tail.append(f"receipt {unit.receipt_hash[:12] if unit.receipt_hash else '—'}")
    if unit.pr_url:
        tail.append(unit.pr_url)
    if not unit.verified:
        tail.append("held, not shipped")
    return f"{' · '.join(bits)} — {', '.join(tail)}"


def render_slack_blocks(card: MissionCard) -> list[dict[str, Any]]:
    """Render *card* to Slack Block Kit JSON.

    Layout: a header, one section per unit with a ✅/⛔ glyph and its
    tests/cost/receipt, per-unit approve/show-diff action rows, and a final
    mission-level actions row (Approve all / Abort).
    """
    header_text = (
        f"Mission {card.mission_id} — "
        f"{card.verified_count}/{card.unit_count} verified, "
        f"{card.held_count} held · total {_fmt_cost(card.total_cost_usd)}"
    )
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text[:150]}}
    ]
    if card.goal:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"*Goal:* {card.goal}"}],
            }
        )

    for unit in card.units:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": _unit_summary(unit)},
            }
        )
        blocks.append(
            {
                "type": "actions",
                "block_id": f"unit:{unit.unit_id}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": f"Approve {unit.unit_id}"},
                        "action_id": _approve_action(unit.unit_id),
                        "value": unit.unit_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Show diff"},
                        "action_id": _show_diff_action(unit.unit_id),
                        "value": unit.unit_id,
                    },
                ],
            }
        )

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "actions",
            "block_id": "mission",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve all"},
                    "style": "primary",
                    "action_id": ACTION_APPROVE_ALL,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Abort"},
                    "style": "danger",
                    "action_id": ACTION_ABORT,
                },
            ],
        }
    )
    return blocks


def render_telegram(card: MissionCard) -> tuple[str, list[list[dict[str, str]]]]:
    """Render *card* to Telegram markdown text + an inline keyboard.

    The keyboard's ``callback_data`` mirrors the Slack ``action_id`` namespace so
    one parser handles both channels.
    """
    lines = [
        f"*Mission {card.mission_id}*",
        f"{card.verified_count}/{card.unit_count} verified · "
        f"{card.held_count} held · total {_fmt_cost(card.total_cost_usd)}",
    ]
    if card.goal:
        lines.append(f"_Goal: {card.goal}_")
    lines.append("")
    for unit in card.units:
        lines.append(_unit_summary(unit))

    keyboard: list[list[dict[str, str]]] = []
    for unit in card.units:
        keyboard.append(
            [
                {
                    "text": f"Approve {unit.unit_id}",
                    "callback_data": _approve_action(unit.unit_id),
                },
                {
                    "text": "Show diff",
                    "callback_data": _show_diff_action(unit.unit_id),
                },
            ]
        )
    keyboard.append(
        [
            {"text": "Approve all", "callback_data": ACTION_APPROVE_ALL},
            {"text": "Abort", "callback_data": ACTION_ABORT},
        ]
    )
    return "\n".join(lines), keyboard


def render_plain(card: MissionCard) -> str:
    """Render *card* to a plain-text terminal fallback."""
    out = [
        f"Mission {card.mission_id}",
        f"  {card.verified_count}/{card.unit_count} verified, "
        f"{card.held_count} held — total cost {_fmt_cost(card.total_cost_usd)}",
    ]
    if card.goal:
        out.append(f"  goal: {card.goal}")
    if not card.units:
        out.append("  (no units)")
    for unit in card.units:
        out.append(f"  {_unit_summary(unit)}")
    return "\n".join(out)
