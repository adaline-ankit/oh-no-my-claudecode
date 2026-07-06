"""Pure, deterministic core for the ``bounty`` feature.

A *bounty board* lets you post point-wagers on tasks, then collect (or forfeit)
the payout when the task is resolved.  Points are the same XP currency as the
quest/arena features — this is the *stakes* layer.

Persistence
-----------
Two files under ``.onmc/bounty/``:

- ``bounties.json``  — the live board: a JSON object mapping bounty ID → bounty
  dict.  Chosen over JSONL so the whole board can be rewritten atomically.
- ``ledger.jsonl``   — append-only claim ledger: one record per claim event,
  recording the payout awarded.  Forfeits are NOT recorded in the ledger (they
  award 0 points); they are reflected by ``status="forfeited"`` in the board.

Payout formula
--------------
::

    payout = reward * DIFFICULTY_MULTIPLIERS[difficulty]

Difficulty multipliers are integer constants so the formula is purely
deterministic without floating-point.  Valid difficulties: ``"easy"``,
``"med"``, ``"hard"`` with multipliers 1×, 2×, 3× respectively.

All functions accept injectable ``bounty_dir: Path`` and ``now_iso: str``
arguments for deterministic, offline testing.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Sub-directory under the repo root where bounty state lives.
BOUNTY_SUBDIR = Path(".onmc") / "bounty"

#: JSON file holding the live bounty board.
BOARD_FILE = "bounties.json"

#: JSONL file holding the claim ledger.
LEDGER_FILE = "ledger.jsonl"

#: Payout multipliers by difficulty.
DIFFICULTY_MULTIPLIERS: dict[str, int] = {
    "easy": 1,
    "med": 2,
    "hard": 3,
}

#: Valid difficulty values (ordered for display).
DIFFICULTIES: tuple[str, ...] = ("easy", "med", "hard")

#: Valid status values.
STATUS_OPEN = "open"
STATUS_CLAIMED = "claimed"
STATUS_FORFEITED = "forfeited"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Bounty:
    """A single posted bounty.

    Fields
    ------
    id:
        Stable UUID identifier.
    task:
        Human-readable task description.
    reward:
        Base reward points posted by the user.
    difficulty:
        One of ``"easy"``, ``"med"``, ``"hard"`` — multiplies the payout.
    status:
        ``"open"``, ``"claimed"``, or ``"forfeited"``.
    posted_at:
        ISO-8601 UTC timestamp when the bounty was created.
    resolved_at:
        ISO-8601 UTC timestamp when claimed/forfeited, or empty string.
    forfeit_reason:
        Optional rationale when forfeited, or empty string.
    payout_awarded:
        Points actually awarded (0 unless claimed).
    """

    id: str
    task: str
    reward: int
    difficulty: str
    status: str
    posted_at: str
    resolved_at: str
    forfeit_reason: str
    payout_awarded: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "id": self.id,
            "task": self.task,
            "reward": self.reward,
            "difficulty": self.difficulty,
            "status": self.status,
            "posted_at": self.posted_at,
            "resolved_at": self.resolved_at,
            "forfeit_reason": self.forfeit_reason,
            "payout_awarded": self.payout_awarded,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Bounty:
        """Reconstruct a Bounty from a stored dict."""
        return cls(
            id=str(d.get("id", "")),
            task=str(d.get("task", "")),
            reward=int(d.get("reward", 0)),
            difficulty=str(d.get("difficulty", "easy")),
            status=str(d.get("status", STATUS_OPEN)),
            posted_at=str(d.get("posted_at", "")),
            resolved_at=str(d.get("resolved_at", "")),
            forfeit_reason=str(d.get("forfeit_reason", "")),
            payout_awarded=int(d.get("payout_awarded", 0)),
        )


# ---------------------------------------------------------------------------
# Payout math
# ---------------------------------------------------------------------------


def payout(reward: int, difficulty: str) -> int:
    """Compute the deterministic payout for a bounty.

    Parameters
    ----------
    reward:
        Base reward points (must be >= 0).
    difficulty:
        One of ``"easy"``, ``"med"``, ``"hard"``.

    Returns
    -------
    int
        ``reward * multiplier`` where multiplier is 1 / 2 / 3 for
        easy / med / hard.

    Raises
    ------
    ValueError
        When ``difficulty`` is not a known value.
    """
    if difficulty not in DIFFICULTY_MULTIPLIERS:
        raise ValueError(
            f"difficulty must be one of {list(DIFFICULTIES)}, got {difficulty!r}"
        )
    return reward * DIFFICULTY_MULTIPLIERS[difficulty]


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------


def _read_board(bounty_dir: Path) -> dict[str, dict[str, Any]]:
    """Read the board JSON file. Returns empty dict when absent."""
    path = bounty_dir / BOARD_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _write_board(bounty_dir: Path, board: dict[str, dict[str, Any]]) -> None:
    """Atomically overwrite the board JSON file."""
    bounty_dir.mkdir(parents=True, exist_ok=True)
    path = bounty_dir / BOARD_FILE
    path.write_text(json.dumps(board, indent=2, sort_keys=True), encoding="utf-8")


def _append_ledger(bounty_dir: Path, record: dict[str, Any]) -> None:
    """Append one JSON line to the claim ledger."""
    bounty_dir.mkdir(parents=True, exist_ok=True)
    path = bounty_dir / LEDGER_FILE
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def _read_ledger(bounty_dir: Path) -> list[dict[str, Any]]:
    """Read all ledger entries. Returns [] when absent or malformed lines skipped."""
    path = bounty_dir / LEDGER_FILE
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if isinstance(entry, dict):
                out.append(entry)
        except json.JSONDecodeError:
            pass
    return out


# ---------------------------------------------------------------------------
# Bounty ID generation (injectable for tests)
# ---------------------------------------------------------------------------


def _new_id() -> str:
    """Generate a short bounty identifier (8 hex chars of a UUID4)."""
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def post(
    task: str,
    reward: int,
    difficulty: str,
    *,
    bounty_dir: Path,
    now_iso: str,
    bounty_id: str | None = None,
) -> Bounty:
    """Post a new bounty to the board.

    Parameters
    ----------
    task:
        Human-readable task description.
    reward:
        Base reward points (must be > 0).
    difficulty:
        One of ``"easy"``, ``"med"``, ``"hard"``.
    bounty_dir:
        Directory where board + ledger files live (injectable for tests).
    now_iso:
        ISO-8601 timestamp (caller-supplied so the core is deterministic).
    bounty_id:
        Optional ID override for tests; otherwise auto-generated.

    Returns
    -------
    Bounty
        The newly posted bounty.

    Raises
    ------
    ValueError
        When ``reward <= 0`` or ``difficulty`` is invalid.
    """
    if reward <= 0:
        raise ValueError(f"reward must be > 0, got {reward}")
    if difficulty not in DIFFICULTY_MULTIPLIERS:
        raise ValueError(
            f"difficulty must be one of {list(DIFFICULTIES)}, got {difficulty!r}"
        )

    bid = bounty_id if bounty_id is not None else _new_id()
    bounty = Bounty(
        id=bid,
        task=task,
        reward=reward,
        difficulty=difficulty,
        status=STATUS_OPEN,
        posted_at=now_iso,
        resolved_at="",
        forfeit_reason="",
        payout_awarded=0,
    )
    board = _read_board(bounty_dir)
    board[bid] = bounty.to_dict()
    _write_board(bounty_dir, board)
    return bounty


def list_bounties(
    *, bounty_dir: Path, status: str | None = None
) -> list[Bounty]:
    """Return bounties from the board, optionally filtered by status.

    Parameters
    ----------
    bounty_dir:
        Board directory (injectable for tests).
    status:
        If given, only return bounties with this status.  ``None`` returns all.

    Returns
    -------
    list[Bounty]
        Bounties in insertion (posted_at) order, oldest first.
    """
    board = _read_board(bounty_dir)
    bounties: list[Bounty] = []
    for entry in board.values():
        b: Bounty | None = None
        with contextlib.suppress(Exception):
            b = Bounty.from_dict(entry)
        if b is not None and (status is None or b.status == status):
            bounties.append(b)
    bounties.sort(key=lambda b: b.posted_at)
    return bounties


def total_pot(*, bounty_dir: Path) -> int:
    """Sum of computed payouts for all open bounties.

    Returns
    -------
    int
        Total potential points available if all open bounties were claimed.
    """
    total = 0
    for b in list_bounties(bounty_dir=bounty_dir, status=STATUS_OPEN):
        with contextlib.suppress(ValueError):
            total += payout(b.reward, b.difficulty)
    return total


def claim(
    bounty_id: str,
    *,
    bounty_dir: Path,
    now_iso: str,
) -> Bounty:
    """Mark a bounty as claimed and record the payout in the ledger.

    Parameters
    ----------
    bounty_id:
        ID of the bounty to claim.
    bounty_dir:
        Board directory (injectable for tests).
    now_iso:
        ISO-8601 timestamp for the claim record.

    Returns
    -------
    Bounty
        Updated bounty with ``status="claimed"`` and ``payout_awarded`` set.

    Raises
    ------
    KeyError
        When ``bounty_id`` is not found on the board.
    ValueError
        When the bounty is not in ``"open"`` status.
    """
    board = _read_board(bounty_dir)
    if bounty_id not in board:
        raise KeyError(f"bounty {bounty_id!r} not found")
    b = Bounty.from_dict(board[bounty_id])
    if b.status != STATUS_OPEN:
        raise ValueError(
            f"bounty {bounty_id!r} is {b.status!r}, not open — cannot claim"
        )

    awarded = payout(b.reward, b.difficulty)
    b = Bounty(
        id=b.id,
        task=b.task,
        reward=b.reward,
        difficulty=b.difficulty,
        status=STATUS_CLAIMED,
        posted_at=b.posted_at,
        resolved_at=now_iso,
        forfeit_reason="",
        payout_awarded=awarded,
    )
    board[bounty_id] = b.to_dict()
    _write_board(bounty_dir, board)

    ledger_record: dict[str, Any] = {
        "bounty_id": bounty_id,
        "task": b.task,
        "payout_awarded": awarded,
        "difficulty": b.difficulty,
        "reward": b.reward,
        "claimed_at": now_iso,
    }
    _append_ledger(bounty_dir, ledger_record)
    return b


def forfeit(
    bounty_id: str,
    *,
    bounty_dir: Path,
    now_iso: str,
    reason: str = "",
) -> Bounty:
    """Close a bounty unpaid.

    Parameters
    ----------
    bounty_id:
        ID of the bounty to forfeit.
    bounty_dir:
        Board directory (injectable for tests).
    now_iso:
        ISO-8601 timestamp for the forfeit event.
    reason:
        Optional human-readable rationale.

    Returns
    -------
    Bounty
        Updated bounty with ``status="forfeited"``.

    Raises
    ------
    KeyError
        When ``bounty_id`` is not found on the board.
    ValueError
        When the bounty is not in ``"open"`` status.
    """
    board = _read_board(bounty_dir)
    if bounty_id not in board:
        raise KeyError(f"bounty {bounty_id!r} not found")
    b = Bounty.from_dict(board[bounty_id])
    if b.status != STATUS_OPEN:
        raise ValueError(
            f"bounty {bounty_id!r} is {b.status!r}, not open — cannot forfeit"
        )

    b = Bounty(
        id=b.id,
        task=b.task,
        reward=b.reward,
        difficulty=b.difficulty,
        status=STATUS_FORFEITED,
        posted_at=b.posted_at,
        resolved_at=now_iso,
        forfeit_reason=reason,
        payout_awarded=0,
    )
    board[bounty_id] = b.to_dict()
    _write_board(bounty_dir, board)
    return b


def balance(*, bounty_dir: Path) -> int:
    """Sum of all payout_awarded values in the claim ledger.

    Parameters
    ----------
    bounty_dir:
        Board directory (injectable for tests).

    Returns
    -------
    int
        Total points earned via claimed bounties.
    """
    total = 0
    for entry in _read_ledger(bounty_dir):
        with contextlib.suppress(ValueError, TypeError):
            total += int(entry.get("payout_awarded", 0))
    return total
