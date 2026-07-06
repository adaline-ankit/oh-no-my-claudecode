"""CLI surface for the ``daily`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time, wiring ``onmc daily`` with **zero** edits to
``cli.py`` or any other shared hub.

``daily`` tracks which calendar **days** (UTC) you were active and rewards
consecutive-day chains — the "don't break the chain" / GitHub contribution
graph model.  This is distinct from ``coach``, which tracks per-event combos
within a single coding session.

Active days come from two sources (union):

1. Explicit check-ins written to ``.onmc/daily/activity.json`` via
   ``onmc daily checkin``.
2. Dates derived from verified run receipts in ``.agent-memory/receipts/``.

State is persisted to ``.onmc/daily/activity.json`` under the repository root.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.daily.chain import (
    GridCell,
    current_streak,
    grid,
    longest_streak,
    milestone,
)

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

_DAILY_SUBDIR = Path(".onmc") / "daily"
_ACTIVITY_FILE = _DAILY_SUBDIR / "activity.json"

_ACTIVE_CHAR = "■"
_INACTIVE_CHAR = "□"
_TODAY_CHAR = "◆"

daily_app = typer.Typer(
    help=(
        "Don't-break-the-chain calendar streak. "
        "Tracks which calendar days you were active and rewards consecutive-day runs."
    ),
    no_args_is_help=False,
    invoke_without_command=True,
)


def _resolve_repo_root() -> Path:
    """Discover the git repo root, or raise typer.Exit(1)."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("error: no git repository found from the current directory.", err=True)
        raise typer.Exit(code=1) from None


def _activity_path(repo_root: Path) -> Path:
    return repo_root / _ACTIVITY_FILE


def _load_checkins(repo_root: Path) -> set[date]:
    """Load explicit check-in dates from ``.onmc/daily/activity.json``."""
    path = _activity_path(repo_root)
    if not path.exists():
        return set()
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return set()
        days_raw = data.get("checkins") or []
        result: set[date] = set()
        for s in days_raw:
            with contextlib.suppress(ValueError):
                result.add(date.fromisoformat(str(s)))
        return result
    except Exception:  # noqa: BLE001
        return set()


def _save_checkins(repo_root: Path, checkins: set[date]) -> None:
    """Persist explicit check-in dates to ``.onmc/daily/activity.json``."""
    path = _activity_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_days = sorted(d.isoformat() for d in checkins)
    path.write_text(json.dumps({"checkins": sorted_days}, indent=2), encoding="utf-8")


def _load_receipt_dates(repo_root: Path) -> set[date]:
    """Derive active days from verified run receipts."""
    try:
        from oh_no_my_claudecode.ledger.accounting import load_receipts

        receipts = load_receipts(repo_root, scope="project")
    except Exception:  # noqa: BLE001
        return set()

    result: set[date] = set()
    for r in receipts:
        if not isinstance(r, dict):
            continue
        if not bool(r.get("verified", False)):
            continue
        ts_raw = r.get("ended_at") or r.get("started_at")
        if not ts_raw:
            continue
        try:
            dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            result.add(dt.astimezone(UTC).date())
        except (ValueError, TypeError):
            pass
    return result


def _active_days(repo_root: Path) -> set[date]:
    """Union of explicit check-ins and receipt-derived active days."""
    return _load_checkins(repo_root) | _load_receipt_dates(repo_root)


def _today_utc() -> date:
    """Return today's UTC date."""
    return datetime.now(UTC).date()


# ---------------------------------------------------------------------------
# Root command — ``onmc daily``
# ---------------------------------------------------------------------------


@daily_app.callback(invoke_without_command=True)
def daily_command(
    ctx: typer.Context,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the result as JSON."),
    ] = False,
) -> None:
    """Show the current chain, longest chain, total active days, and next milestone.

    Displays a summary of your don't-break-the-chain calendar streak.

    Examples:

        onmc daily

        onmc daily --json
    """
    if ctx.invoked_subcommand is not None:
        return

    repo_root = _resolve_repo_root()
    days = _active_days(repo_root)
    today = _today_utc()

    cur = current_streak(days, today=today)
    lng = longest_streak(days)
    total = len(days)
    next_milestone = milestone(cur)
    days_until: int | None = (next_milestone - cur) if next_milestone is not None else None

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": "daily_status",
                    "current_streak": cur,
                    "longest_streak": lng,
                    "total_active_days": total,
                    "next_milestone": next_milestone,
                    "days_until_next_milestone": days_until,
                    "today": today.isoformat(),
                },
                indent=2,
            )
        )
        return

    streak_bar = "🔥" * min(cur, 10) if cur else "  (no active streak)"
    typer.echo("")
    typer.echo(f"  current streak     : {cur} day(s)  {streak_bar}")
    typer.echo(f"  longest streak     : {lng} day(s)")
    typer.echo(f"  total active days  : {total}")
    if next_milestone is not None:
        typer.echo(f"  next milestone     : {next_milestone} days  ({days_until} to go)")
    else:
        typer.echo("  next milestone     : beyond 100 — legendary!")
    typer.echo("")


# ---------------------------------------------------------------------------
# ``onmc daily grid``
# ---------------------------------------------------------------------------


@daily_app.command("grid")
def grid_command(
    weeks: Annotated[
        int,
        typer.Option("--weeks", "-w", help="Number of weeks to show (default 12)."),
    ] = 12,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the grid as JSON."),
    ] = False,
) -> None:
    """Show a contribution-grid-style calendar of active days.

    Renders the last WEEKS calendar weeks, marking active days with a filled
    block (■) and inactive days with an open block (□).  Today is marked
    with a diamond (◆).

    Examples:

        onmc daily grid

        onmc daily grid --weeks 4

        onmc daily grid --json
    """
    if weeks < 1:
        typer.echo("error: --weeks must be >= 1.", err=True)
        raise typer.Exit(code=1)

    repo_root = _resolve_repo_root()
    days = _active_days(repo_root)
    today = _today_utc()

    rows: list[list[GridCell]] = grid(days, today=today, weeks=weeks)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": "daily_grid",
                    "weeks": weeks,
                    "today": today.isoformat(),
                    "rows": [
                        [
                            {
                                "day": cell.day.isoformat(),
                                "active": cell.active,
                                "is_today": cell.is_today,
                            }
                            for cell in row
                        ]
                        for row in rows
                    ],
                },
                indent=2,
            )
        )
        return

    # Header: month labels aligned to grid columns.
    header_parts: list[str] = []
    for row in rows:
        mon = row[0].day
        label = mon.strftime("%b") if mon.day <= 7 else "   "
        header_parts.append(label[:3])
    typer.echo("  " + " ".join(header_parts))

    # Day rows: Mon–Sun (one row per day-of-week across all weeks).
    day_names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    for dow in range(7):
        cells_for_row: list[str] = []
        for row in rows:
            cell = row[dow]
            if cell.is_today:
                ch = _TODAY_CHAR
            elif cell.active:
                ch = _ACTIVE_CHAR
            else:
                ch = _INACTIVE_CHAR
            cells_for_row.append(ch)
        typer.echo(f"{day_names[dow]}  " + "   ".join(cells_for_row))

    active_count = sum(1 for row in rows for cell in row if cell.active)
    typer.echo(f"\n  {active_count} active day(s) in the last {weeks} week(s).")


# ---------------------------------------------------------------------------
# ``onmc daily checkin``
# ---------------------------------------------------------------------------


@daily_app.command("checkin")
def checkin_command(
    day: Annotated[
        str | None,
        typer.Option(
            "--date",
            help="Date to mark active (YYYY-MM-DD). Defaults to today (UTC).",
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the check-in result as JSON."),
    ] = False,
) -> None:
    """Mark a calendar day active (persist to .onmc/daily/activity.json).

    By default marks today (UTC) as active.  Explicit --date allows
    back-filling a day you forgot to check in.

    Examples:

        onmc daily checkin

        onmc daily checkin --date 2024-03-15

        onmc daily checkin --json
    """
    today = _today_utc()

    if day is not None:
        try:
            checkin_date = date.fromisoformat(day)
        except ValueError:
            typer.echo(f"error: --date must be in YYYY-MM-DD format, got {day!r}.", err=True)
            raise typer.Exit(code=1) from None
    else:
        checkin_date = today

    repo_root = _resolve_repo_root()
    checkins = _load_checkins(repo_root)
    already_present = checkin_date in checkins
    checkins.add(checkin_date)
    _save_checkins(repo_root, checkins)

    # Recompute streak with updated checkins + receipt dates.
    days = checkins | _load_receipt_dates(repo_root)
    cur = current_streak(days, today=today)
    next_m = milestone(cur)
    days_until: int | None = (next_m - cur) if next_m is not None else None

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": "daily_checkin",
                    "date": checkin_date.isoformat(),
                    "already_present": already_present,
                    "current_streak": cur,
                    "next_milestone": next_m,
                    "days_until_next_milestone": days_until,
                },
                indent=2,
            )
        )
        return

    verb = "Already marked" if already_present else "Checked in"
    typer.echo(f"{verb}: {checkin_date.isoformat()}  (current streak: {cur} day(s))")
    if next_m is not None:
        typer.echo(f"  next milestone: {next_m} days  ({days_until} to go)")


# ---------------------------------------------------------------------------
# Auto-discovery entry point
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Register the ``onmc daily`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(daily_app, name="daily")
