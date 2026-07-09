"""Load / save the ``onmc budget`` cap configuration.

The cap lives in ``.onmc/budget.json`` (JSON, distinct from the shared
``.onmc/config.yaml`` so the guard never risks corrupting the main config). Its
shape::

    {"cap_usd": 25.0, "window": "day", "warn_ratio": 0.8}

A missing file, unreadable file, or ``cap_usd: null`` all resolve to an
*unlimited* config (``cap_usd is None``) — the deny-nothing default that keeps
the guard off until an operator explicitly sets a cap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: Valid rolling-window labels.
VALID_WINDOWS = ("day", "week", "all")

#: Default window when none is configured.
DEFAULT_WINDOW = "day"

#: Default warn threshold as a fraction of the cap.
DEFAULT_WARN_RATIO = 0.8

#: Config filename under ``.onmc/``.
CONFIG_FILENAME = "budget.json"


@dataclass(frozen=True)
class BudgetConfig:
    """Resolved budget-cap configuration.

    Fields
    ------
    cap_usd:
        The hard cap in dollars, or ``None`` for unlimited (guard off).
    window:
        Rolling window the spend is summed over (``"day"`` | ``"week"`` |
        ``"all"``).
    warn_ratio:
        Fraction of the cap at which to raise a ``warn`` state.
    """

    cap_usd: float | None = None
    window: str = DEFAULT_WINDOW
    warn_ratio: float = DEFAULT_WARN_RATIO


def budget_config_path(repo_root: Path) -> Path:
    """Return the path to ``.onmc/budget.json`` under *repo_root*."""
    return repo_root / ".onmc" / CONFIG_FILENAME


def _coerce_window(value: object) -> str:
    """Return a valid window label, falling back to the default."""
    if isinstance(value, str) and value in VALID_WINDOWS:
        return value
    return DEFAULT_WINDOW


def _coerce_warn_ratio(value: object) -> float:
    """Return a warn ratio clamped to ``[0.0, 1.0]``, defaulting on bad input."""
    try:
        ratio = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_WARN_RATIO
    return min(1.0, max(0.0, ratio))


def _coerce_cap(value: object) -> float | None:
    """Return a non-negative cap, or ``None`` for unlimited / bad input."""
    if value is None:
        return None
    try:
        cap = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return cap if cap >= 0 else None


def load_budget_config(repo_root: Path) -> BudgetConfig:
    """Load the budget config for *repo_root*.

    Missing / unreadable / malformed config → an unlimited :class:`BudgetConfig`
    (``cap_usd is None``). Never raises.
    """
    path = budget_config_path(repo_root)
    if not path.exists():
        return BudgetConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return BudgetConfig()
    if not isinstance(raw, dict):
        return BudgetConfig()
    return BudgetConfig(
        cap_usd=_coerce_cap(raw.get("cap_usd")),
        window=_coerce_window(raw.get("window")),
        warn_ratio=_coerce_warn_ratio(raw.get("warn_ratio")),
    )


def save_budget_config(repo_root: Path, config: BudgetConfig) -> Path:
    """Write *config* to ``.onmc/budget.json`` idempotently.

    Creates ``.onmc/`` if needed. Returns the written path. Deterministic
    serialisation (sorted keys) so repeated saves of the same config produce an
    identical file.
    """
    path = budget_config_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cap_usd": config.cap_usd,
        "window": config.window,
        "warn_ratio": config.warn_ratio,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def set_cap(
    repo_root: Path,
    cap_usd: float | None,
    window: str = DEFAULT_WINDOW,
    warn_ratio: float = DEFAULT_WARN_RATIO,
) -> Path:
    """Set the cap config and persist it. Returns the written config path.

    Args:
        repo_root: Repository root (``.onmc/`` is created as needed).
        cap_usd: The hard cap in dollars, or ``None`` to disable the guard.
            Negative values are coerced to ``None``.
        window: Rolling window label; invalid values fall back to the default.
        warn_ratio: Warn threshold fraction, clamped to ``[0.0, 1.0]``.
    """
    config = BudgetConfig(
        cap_usd=_coerce_cap(cap_usd),
        window=_coerce_window(window),
        warn_ratio=_coerce_warn_ratio(warn_ratio),
    )
    return save_budget_config(repo_root, config)


__all__ = [
    "CONFIG_FILENAME",
    "DEFAULT_WARN_RATIO",
    "DEFAULT_WINDOW",
    "VALID_WINDOWS",
    "BudgetConfig",
    "budget_config_path",
    "load_budget_config",
    "save_budget_config",
    "set_cap",
]
