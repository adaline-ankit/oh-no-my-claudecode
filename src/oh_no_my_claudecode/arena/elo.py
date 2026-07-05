"""Pure, deterministic ELO rating math for ``onmc arena``.

Standard ELO formula (no external deps, no I/O, no randomness):

    expected_a = 1 / (1 + 10 ** ((rb - ra) / 400))
    ra' = ra + K * (score_a - expected_a)
    rb' = rb + K * (score_b - expected_b)

where ``score_a`` is 1 for a win, 0.5 for a draw, 0 for a loss (and vice
versa for ``score_b``).

Persistence layout
------------------
Bouts are appended to ``.onmc/arena/bouts.jsonl`` (one JSON object per line).
Ratings are **always recomputed** from the full bouts log via
:func:`build_ledger` — never stored as a source of truth — so the file can
never drift from the deterministic formula (same pattern as ``registry``).
The computed ratings *snapshot* is written to ``.onmc/arena/ratings.json`` for
fast look-ups, but it is treated as a derived cache, not the authoritative
state.

Tie-breaking
------------
When two models share the same ELO rating, the model whose name is
lexicographically smaller sorts first.  This is the only stable, deterministic
total order available without timestamps (which are excluded from rating math).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RATING: float = 1000.0
"""Starting ELO rating assigned to a model the first time it appears."""

DEFAULT_K: float = 32.0
"""K-factor: controls how much a single bout moves the ratings.

Standard tournament value.  Higher K → faster convergence, more volatility.
"""

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Bout:
    """One head-to-head matchup between two models.

    Attributes
    ----------
    model_a:
        Name / identifier of the first model.
    model_b:
        Name / identifier of the second model.
    winner:
        ``"A"`` if model_a won, ``"B"`` if model_b won, ``"draw"`` otherwise.
    task:
        Optional free-text task description (for filtering / display).
    """

    model_a: str
    model_b: str
    winner: str  # "A" | "B" | "draw"
    task: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of this bout."""
        return {
            "model_a": self.model_a,
            "model_b": self.model_b,
            "winner": self.winner,
            "task": self.task,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Bout:
        """Construct a :class:`Bout` from a dict (tolerant of missing keys)."""
        return cls(
            model_a=str(d.get("model_a") or ""),
            model_b=str(d.get("model_b") or ""),
            winner=str(d.get("winner") or "draw"),
            task=str(d.get("task") or ""),
        )


@dataclass
class ModelRecord:
    """One model's aggregated ELO record.

    Attributes
    ----------
    model:
        Model identifier.
    rating:
        Current ELO rating (recomputed from all bouts).
    wins / losses / draws:
        Bout outcome tallies.
    bouts:
        Total bouts (= wins + losses + draws).
    rating_history:
        ELO after each bout, in order.  Lets callers reconstruct how the
        rating evolved.  The initial rating (before any bouts) is **not**
        included — history[0] is the rating after bout 0.
    """

    model: str
    rating: float = DEFAULT_RATING
    wins: int = 0
    losses: int = 0
    draws: int = 0
    bouts: int = 0
    rating_history: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of this record."""
        return {
            "model": self.model,
            "rating": round(self.rating, 4),
            "wins": self.wins,
            "losses": self.losses,
            "draws": self.draws,
            "bouts": self.bouts,
            "rating_history": [round(r, 4) for r in self.rating_history],
        }


@dataclass
class Ledger:
    """In-memory arena ledger: all bouts + per-model records.

    Built by :func:`build_ledger` from a list of :class:`Bout` objects.
    Never mutate directly — rebuild from bouts to keep the recompute-from-source
    guarantee.
    """

    models: dict[str, ModelRecord] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot (sorted by model name)."""
        return {
            "models": {
                model: rec.to_dict()
                for model, rec in sorted(self.models.items())
            }
        }


# ---------------------------------------------------------------------------
# Pure ELO math
# ---------------------------------------------------------------------------


def _expected(rating_a: float, rating_b: float) -> float:
    """Expected score for model_a given ratings (standard ELO formula)."""
    return 1.0 / (1.0 + math.pow(10.0, (rating_b - rating_a) / 400.0))


def update_elo(
    ra: float,
    rb: float,
    outcome: str,
    *,
    k: float = DEFAULT_K,
) -> tuple[float, float]:
    """Compute new ELO ratings after one bout.

    Parameters
    ----------
    ra:
        Current rating of model A.
    rb:
        Current rating of model B.
    outcome:
        ``"A"`` — model A won; ``"B"`` — model B won; anything else — draw.
    k:
        K-factor (default :data:`DEFAULT_K` = 32).

    Returns
    -------
    tuple[float, float]
        ``(new_ra, new_rb)`` after the bout.

    Examples
    --------
    >>> ra, rb = update_elo(1000.0, 1000.0, "A")
    >>> ra > 1000.0 and rb < 1000.0
    True
    >>> ra2, rb2 = update_elo(1000.0, 1000.0, "draw")
    >>> ra2 == 1000.0 and rb2 == 1000.0
    True
    """
    ea = _expected(ra, rb)
    eb = 1.0 - ea  # expected_b = 1 - expected_a (they sum to 1)

    if outcome == "A":
        sa, sb = 1.0, 0.0
    elif outcome == "B":
        sa, sb = 0.0, 1.0
    else:
        sa, sb = 0.5, 0.5

    new_ra = ra + k * (sa - ea)
    new_rb = rb + k * (sb - eb)
    return new_ra, new_rb


# ---------------------------------------------------------------------------
# Ledger construction (pure, recompute-from-bouts)
# ---------------------------------------------------------------------------


def _ensure_model(ledger: Ledger, name: str) -> ModelRecord:
    """Return the ModelRecord for *name*, creating it at DEFAULT_RATING if absent."""
    if name not in ledger.models:
        ledger.models[name] = ModelRecord(model=name, rating=DEFAULT_RATING)
    return ledger.models[name]


def _apply_bout(ledger: Ledger, bout: Bout, k: float = DEFAULT_K) -> None:
    """Fold one :class:`Bout` into *ledger* in place (pure — no I/O)."""
    rec_a = _ensure_model(ledger, bout.model_a)
    rec_b = _ensure_model(ledger, bout.model_b)

    new_ra, new_rb = update_elo(rec_a.rating, rec_b.rating, bout.winner, k=k)

    rec_a.rating = new_ra
    rec_b.rating = new_rb
    rec_a.bouts += 1
    rec_b.bouts += 1
    rec_a.rating_history.append(new_ra)
    rec_b.rating_history.append(new_rb)

    if bout.winner == "A":
        rec_a.wins += 1
        rec_b.losses += 1
    elif bout.winner == "B":
        rec_a.losses += 1
        rec_b.wins += 1
    else:
        rec_a.draws += 1
        rec_b.draws += 1


def build_ledger(bouts: list[Bout], k: float = DEFAULT_K) -> Ledger:
    """Fold a list of bouts into a fresh :class:`Ledger`.

    Pure and deterministic.  The same bouts always produce the same ledger,
    byte-for-byte.  An empty list yields an empty ledger (no fabricated
    defaults).

    Parameters
    ----------
    bouts:
        Ordered list of :class:`Bout` objects (oldest first).
    k:
        K-factor (default :data:`DEFAULT_K`).

    Returns
    -------
    Ledger
        Aggregated ELO state.
    """
    ledger = Ledger()
    for bout in bouts:
        # Skip malformed bouts silently (tolerant)
        if not bout.model_a or not bout.model_b:
            continue
        _apply_bout(ledger, bout, k=k)
    return ledger


def rank_ledger(ledger: Ledger) -> list[ModelRecord]:
    """Return models ranked by ELO rating desc, stable tiebreak by model name.

    A total, deterministic ordering: ties on ``rating`` break alphabetically by
    ``model`` so the leaderboard is reproducible across runs and machines.

    Parameters
    ----------
    ledger:
        The arena ledger to rank.

    Returns
    -------
    list[ModelRecord]
        Models, highest ELO first.
    """
    return sorted(
        ledger.models.values(),
        key=lambda r: (-r.rating, r.model),
    )


# ---------------------------------------------------------------------------
# I/O helpers (tolerant boundary)
# ---------------------------------------------------------------------------


def load_bouts(path: Any) -> list[Bout]:
    """Load bouts from a JSONL file (one JSON object per line, tolerant).

    Missing file, blank lines, and malformed JSON lines are silently skipped.

    Parameters
    ----------
    path:
        Path-like to the ``.onmc/arena/bouts.jsonl`` file.

    Returns
    -------
    list[Bout]
        Parsed bouts, in file order (oldest first).
    """
    from pathlib import Path  # noqa: PLC0415 - keep module import surface minimal

    p = Path(path)
    if not p.exists():
        return []
    bouts: list[Bout] = []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            if isinstance(d, dict):
                bouts.append(Bout.from_dict(d))
        except (json.JSONDecodeError, ValueError):
            continue
    return bouts


def append_bout(path: Any, bout: Bout) -> None:
    """Append one :class:`Bout` as a JSONL line to *path*, creating parents.

    Parameters
    ----------
    path:
        Path-like to ``.onmc/arena/bouts.jsonl``.
    bout:
        The bout to persist.
    """
    from pathlib import Path  # noqa: PLC0415

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(bout.to_dict(), sort_keys=True) + "\n")


def save_ratings(path: Any, ledger: Ledger) -> None:
    """Write the ratings snapshot JSON to *path* (derived cache, not truth).

    Parameters
    ----------
    path:
        Path-like to ``.onmc/arena/ratings.json``.
    ledger:
        The current ledger (always recomputed from bouts before calling).
    """
    from pathlib import Path  # noqa: PLC0415

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"version": 1, **ledger.to_dict()}, indent=2, sort_keys=True),
        encoding="utf-8",
    )


__all__ = [
    "DEFAULT_K",
    "DEFAULT_RATING",
    "Bout",
    "Ledger",
    "ModelRecord",
    "append_bout",
    "build_ledger",
    "load_bouts",
    "rank_ledger",
    "save_ratings",
    "update_elo",
]
