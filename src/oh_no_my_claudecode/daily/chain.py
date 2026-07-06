"""Pure calendar-day streak engine for ``onmc daily``.

Design principles
-----------------
- **Deterministic**: all functions accept ``today: date`` as an explicit
  parameter.  No wall-clock reads, no ``datetime.now()`` inside this module.
- **Pure**: zero I/O.  All side-effects are confined to ``commands.py``.
- **Honest**: only days present in ``active_days`` count.  No padding or
  interpolation.

Streak definition
-----------------
A *current streak* is the longest unbroken consecutive-day chain ending on
(or including) ``today``.

  - If ``today`` is in ``active_days``, the chain includes today and extends
    backwards through every consecutive prior active day.
  - If ``today`` is NOT in ``active_days`` but ``today - 1 day`` IS, the chain
    still extends from yesterday backwards (the day is not yet over — the user
    may still check in today).  This is the "grace period" rule: a chain is
    only broken when there is a genuine gap, not merely because today's
    check-in hasn't happened yet.  This rule is documented and tested.
  - If neither today nor yesterday is active, the current streak is 0.

Milestones
----------
The next milestone above the current streak is the lowest of 7 / 30 / 100
that is strictly greater than the current streak.  If the current streak
exceeds 100, ``None`` is returned (no next milestone).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Current streak
# ---------------------------------------------------------------------------


def current_streak(active_days: Collection[date], *, today: date) -> int:
    """Return the length of the current consecutive-day chain.

    Parameters
    ----------
    active_days:
        Any collection of :class:`datetime.date` objects marking active days.
    today:
        The reference date (injected by the command layer — never read from
        the wall clock inside this function).

    Returns
    -------
    int
        Length of the current streak.  0 when neither today nor yesterday
        is active (chain is broken).

    Notes
    -----
    See module docstring for the "grace period" rule: if today is not yet
    marked active, the chain is measured from yesterday to allow the user
    to check in during the current day without prematurely breaking the run.
    """
    day_set: frozenset[date] = frozenset(active_days)

    # Determine the anchor: today if active; yesterday as a grace period.
    if today in day_set:
        anchor = today
    elif (today - timedelta(days=1)) in day_set:
        anchor = today - timedelta(days=1)
    else:
        return 0

    streak = 0
    cursor = anchor
    while cursor in day_set:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


# ---------------------------------------------------------------------------
# Longest streak (over entire history)
# ---------------------------------------------------------------------------


def longest_streak(active_days: Collection[date]) -> int:
    """Return the longest consecutive-day chain anywhere in *active_days*.

    Parameters
    ----------
    active_days:
        Any collection of :class:`datetime.date` objects.

    Returns
    -------
    int
        Length of the longest run of consecutive days.  0 for an empty input.
    """
    day_set: frozenset[date] = frozenset(active_days)
    if not day_set:
        return 0

    best = 0
    for d in day_set:
        # Only start counting from the *beginning* of a run (no predecessor).
        if (d - timedelta(days=1)) in day_set:
            continue
        run = 0
        cursor = d
        while cursor in day_set:
            run += 1
            cursor += timedelta(days=1)
        if run > best:
            best = run
    return best


# ---------------------------------------------------------------------------
# Contribution-grid cell
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GridCell:
    """One cell in the contribution grid.

    Attributes
    ----------
    day:
        The calendar date this cell represents.
    active:
        Whether this day is in the active set.
    is_today:
        Whether this day equals the injected *today*.
    """

    day: date
    active: bool
    is_today: bool


def grid(
    active_days: Collection[date],
    *,
    today: date,
    weeks: int = 12,
) -> list[list[GridCell]]:
    """Build a contribution-grid covering the last *weeks* calendar weeks.

    The grid is a list of *weeks* rows, each containing 7 :class:`GridCell`
    objects (Monday … Sunday).  The rightmost column always ends on the
    Sunday on or after *today*.

    Parameters
    ----------
    active_days:
        Active day set.
    today:
        Reference date (injected, never from wall clock).
    weeks:
        Number of weeks to include (default 12).

    Returns
    -------
    list[list[GridCell]]
        Outer list = weeks (oldest first); inner list = days Mon–Sun.
    """
    day_set: frozenset[date] = frozenset(active_days)

    # Find the Sunday that ends the grid (on or after today).
    days_until_sunday = (6 - today.weekday()) % 7  # Monday=0, Sunday=6
    grid_end = today + timedelta(days=days_until_sunday)
    grid_start = grid_end - timedelta(weeks=weeks) + timedelta(days=1)

    rows: list[list[GridCell]] = []
    cursor = grid_start
    while cursor <= grid_end:
        week_cells: list[GridCell] = []
        for _ in range(7):
            week_cells.append(
                GridCell(day=cursor, active=cursor in day_set, is_today=cursor == today)
            )
            cursor += timedelta(days=1)
        rows.append(week_cells)
    return rows


# ---------------------------------------------------------------------------
# Milestone
# ---------------------------------------------------------------------------

_MILESTONES: tuple[int, ...] = (7, 30, 100)


def milestone(streak: int) -> int | None:
    """Return the next milestone above *streak*, or ``None`` if past all.

    Milestones are 7, 30, and 100 (days).

    Parameters
    ----------
    streak:
        Current streak length.

    Returns
    -------
    int | None
        Lowest milestone strictly greater than *streak*; ``None`` if streak
        exceeds all milestones.
    """
    for m in _MILESTONES:
        if streak < m:
            return m
    return None
