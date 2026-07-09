"""Pure, deterministic budget-guard core for ``onmc budget``.

This module answers *may a new run proceed under the configured cap?* It is the
enforcement counterpart to the read-only :mod:`oh_no_my_claudecode.cost` report
and the byte-oriented :mod:`oh_no_my_claudecode.membudget` — see the package
docstring for the distinction.

Design notes
------------
- **Pure core**: :func:`evaluate` takes an already-summed spend, a cap, and a
  warn ratio — it never touches the clock, filesystem, or network.
  :func:`check_budget` is the thin impure boundary: it loads the cap config and
  receipts, then delegates the spend summation to
  :func:`oh_no_my_claudecode.cost.cost.build_cost_report` (the reused compiler)
  and the decision to :func:`evaluate`.
- **Deny-nothing by default**: a missing / unconfigured cap (``cap_usd`` is
  ``None``) always yields an ``ok`` + allowed decision. The guard NEVER blocks a
  run it was not explicitly told to cap.
- **Deterministic**: same receipts + same ``now_ms`` + same config → identical
  :class:`BudgetDecision`. ``now_ms`` is injectable so tests never read the
  clock.
- **Window filtering** is delegated to ``build_cost_report`` (which filters
  receipts by timestamp against a trailing window ending at ``now``); ``budget``
  only maps the ``day`` / ``week`` / ``all`` label to that window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from oh_no_my_claudecode.cost.cost import build_cost_report

Window = Literal["day", "week", "all"]
State = Literal["ok", "warn", "blocked"]

#: Trailing window sizes, in days, for the fixed labels.
_WINDOW_DAYS: dict[str, int] = {"day": 1, "week": 7}

#: Default warn threshold as a fraction of the cap.
DEFAULT_WARN_RATIO = 0.8


@dataclass(frozen=True)
class BudgetDecision:
    """The verdict of a single budget check.

    Fields
    ------
    allowed:
        ``True`` when a new run may proceed. ``False`` only in the ``blocked``
        state (spend has reached or exceeded the cap).
    spend_usd:
        Known spend summed over the window (rounded to 4 dp). Never fabricated —
        receipts with no ``cost_usd`` contribute nothing.
    cap_usd:
        The configured hard cap, or ``None`` when no cap is set (unlimited).
    ratio:
        ``spend_usd / cap_usd`` rounded to 4 dp. ``0.0`` when there is no cap.
    state:
        ``"ok"`` | ``"warn"`` | ``"blocked"``. ``warn`` and ``blocked`` only
        occur when a cap is set.
    window:
        The window the spend was summed over (``"day"`` | ``"week"`` | ``"all"``).
    reason:
        Short human-readable explanation of the verdict.
    """

    allowed: bool
    spend_usd: float
    cap_usd: float | None
    ratio: float
    state: State
    window: str
    reason: str


def evaluate(
    spend_usd: float,
    cap_usd: float | None,
    *,
    warn_ratio: float = DEFAULT_WARN_RATIO,
    window: str = "all",
) -> BudgetDecision:
    """Decide the budget state from an already-summed *spend_usd* and *cap_usd*.

    Pure and deterministic — no I/O, no clock. This is the single source of the
    threshold logic:

    - ``cap_usd is None`` → ``ok`` + allowed (deny-nothing; the guard is off).
    - ``spend_usd >= cap_usd`` → ``blocked`` + not allowed (boundary is a block).
    - ``spend_usd >= warn_ratio * cap_usd`` → ``warn`` + allowed.
    - otherwise → ``ok`` + allowed.

    Args:
        spend_usd: Known spend over the window (dollars).
        cap_usd: The hard cap, or ``None`` for unlimited.
        warn_ratio: Fraction of the cap at which to raise ``warn`` (default
            :data:`DEFAULT_WARN_RATIO`). Clamped to ``[0.0, 1.0]``.
        window: Window label to record on the decision (informational).

    Returns:
        A frozen :class:`BudgetDecision`.
    """
    spend = round(max(0.0, spend_usd), 4)

    if cap_usd is None:
        return BudgetDecision(
            allowed=True,
            spend_usd=spend,
            cap_usd=None,
            ratio=0.0,
            state="ok",
            window=window,
            reason="no cap configured — budget guard is off (deny-nothing)",
        )

    warn = min(1.0, max(0.0, warn_ratio))
    ratio = round(spend / cap_usd, 4) if cap_usd > 0 else 1.0

    if spend >= cap_usd:
        return BudgetDecision(
            allowed=False,
            spend_usd=spend,
            cap_usd=cap_usd,
            ratio=ratio,
            state="blocked",
            window=window,
            reason=(
                f"BLOCKED: spend ${spend:.2f} has reached the cap "
                f"${cap_usd:.2f} for this {window} window"
            ),
        )
    if spend >= warn * cap_usd:
        return BudgetDecision(
            allowed=True,
            spend_usd=spend,
            cap_usd=cap_usd,
            ratio=ratio,
            state="warn",
            window=window,
            reason=(
                f"WARNING: spend ${spend:.2f} is at {ratio:.0%} of the "
                f"${cap_usd:.2f} cap (warn at {warn:.0%})"
            ),
        )
    return BudgetDecision(
        allowed=True,
        spend_usd=spend,
        cap_usd=cap_usd,
        ratio=ratio,
        state="ok",
        window=window,
        reason=f"spend ${spend:.2f} is within the ${cap_usd:.2f} cap",
    )


def _now(now_ms: int | None) -> datetime:
    """Resolve the reference instant from an optional injected epoch-ms value."""
    if now_ms is None:
        return datetime.now(UTC)
    return datetime.fromtimestamp(now_ms / 1000.0, UTC)


def _span_days(receipts: list[dict[str, Any]], now: datetime) -> int:
    """Days from the earliest dated receipt to *now* (for the ``all`` window).

    Bounds the trailing window ``build_cost_report`` zero-fills so the ``all``
    label covers every receipt without an unbounded day range. Timestamps are
    read via ``cost``'s own parser so we never introduce a second receipt
    schema.
    """
    from oh_no_my_claudecode.cost.cost import _receipt_when  # reuse cost's parser

    earliest: datetime | None = None
    for raw in receipts:
        if not isinstance(raw, dict):
            continue
        when = _receipt_when(raw)
        if when is None:
            continue
        if earliest is None or when < earliest:
            earliest = when
    if earliest is None:
        return 1
    delta_days = (now - earliest).total_seconds() / 86400.0
    return max(1, int(delta_days) + 1)


def _window_days(window: str, receipts: list[dict[str, Any]], now: datetime) -> int:
    """Map a window label to the trailing day count for ``build_cost_report``."""
    if window in _WINDOW_DAYS:
        return _WINDOW_DAYS[window]
    return _span_days(receipts, now)


def sum_spend(
    receipts: list[dict[str, Any]],
    *,
    window: str,
    now: datetime,
) -> float:
    """Sum known spend over *window* by reusing ``cost``'s receipt compiler.

    Delegates window filtering and cost summation to
    :func:`oh_no_my_claudecode.cost.cost.build_cost_report` — we do not re-parse
    receipts here. Returns the window's ``total_cost_usd``.
    """
    days = _window_days(window, receipts, now)
    report = build_cost_report(receipts, now=now, days=days)
    return report.total_cost_usd


def check_budget(repo_root: Path, *, now_ms: int | None = None) -> BudgetDecision:
    """Load the cap config + receipts and return the current budget verdict.

    The thin impure boundary over :func:`evaluate`. Steps:

    1. Load ``.onmc/budget.json`` (missing → unlimited/OK; never blocks).
    2. Load run receipts from ``.agent-memory/receipts/``.
    3. Sum known spend over the configured window (reusing ``cost``).
    4. Delegate the verdict to :func:`evaluate`.

    Args:
        repo_root: Repository root containing ``.onmc/`` and ``.agent-memory/``.
        now_ms: Injectable reference instant (Unix epoch milliseconds). Defaults
            to the current UTC time. Used for deterministic window filtering.

    Returns:
        A frozen :class:`BudgetDecision`.
    """
    from oh_no_my_claudecode.budget.config import load_budget_config
    from oh_no_my_claudecode.ledger.accounting import load_receipts

    config = load_budget_config(repo_root)
    now = _now(now_ms)

    if config.cap_usd is None:
        # Deny-nothing fast path: never even read receipts when uncapped.
        return evaluate(0.0, None, warn_ratio=config.warn_ratio, window=config.window)

    receipts = load_receipts(repo_root, scope="project", now=now)
    spend = sum_spend(receipts, window=config.window, now=now)
    return evaluate(
        spend,
        config.cap_usd,
        warn_ratio=config.warn_ratio,
        window=config.window,
    )


__all__ = [
    "DEFAULT_WARN_RATIO",
    "BudgetDecision",
    "State",
    "Window",
    "check_budget",
    "evaluate",
    "sum_spend",
]
