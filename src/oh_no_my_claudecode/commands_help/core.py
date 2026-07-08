"""Pure-logic helpers for ``onmc commands`` help tiering.

Separated from the Typer surface so they can be tested without importing the
CLI or registering any commands.  The only external dependency is stdlib.

Design
------
- ``CATEGORY_MAP``: maintained dict ``command-name → category``.  Any command
  name absent from the map automatically lands in ``"Other"``, so new commands
  added to the app remain discoverable without a forced update here.
- ``group_commands(names)``: pure function; deterministic (sorted within each
  category); returns the full set of categories even when some are empty so
  callers can iterate without key-existence checks.
"""

from __future__ import annotations

from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Category order (display sequence)
# ---------------------------------------------------------------------------

CATEGORY_ORDER: list[str] = [
    "Core",
    "Orchestrate",
    "Memory",
    "Trust",
    "Fun",
    "Integrations",
    "Other",
]

# ---------------------------------------------------------------------------
# Core commands — shown in the root epilog
# ---------------------------------------------------------------------------

CORE_COMMANDS: list[str] = [
    "setup",
    "wrap",
    "autopilot",
    "brief",
    "recall",
    "ui",
    "init",
]

# ---------------------------------------------------------------------------
# Category map — command-name → category
# ---------------------------------------------------------------------------
# Anything not listed here falls through to "Other" automatically.
# "quickstart" is reserved so it lands in Core once that branch merges.

CATEGORY_MAP: dict[str, str] = {
    # ── Core ─────────────────────────────────────────────────────────────
    "setup": "Core",
    "quickstart": "Core",
    "wrap": "Core",
    "autopilot": "Core",
    "brief": "Core",
    "recall": "Core",
    "ui": "Core",
    "init": "Core",
    # ── Orchestrate ───────────────────────────────────────────────────────
    "mission": "Orchestrate",
    "swarm": "Orchestrate",
    "refinery": "Orchestrate",
    "land": "Orchestrate",
    "nightshift": "Orchestrate",
    "loop": "Orchestrate",
    "loop-templates": "Orchestrate",
    "missioncontrol": "Orchestrate",
    "autoroute": "Orchestrate",
    "swarmreplay": "Orchestrate",
    # ── Memory ────────────────────────────────────────────────────────────
    "memory": "Memory",
    "memory-diff": "Memory",
    "memstage": "Memory",
    "membudget": "Memory",
    "memprovider": "Memory",
    "memguard": "Memory",
    "session-search": "Memory",
    "consolidate": "Memory",
    "ingest": "Memory",
    "digest": "Memory",
    "capture": "Memory",
    "mine": "Memory",
    "sync": "Memory",
    "pull": "Memory",
    # ── Trust ─────────────────────────────────────────────────────────────
    "attest": "Trust",
    "registry": "Trust",
    "registry-demo": "Trust",
    "badge": "Trust",
    "scorecard": "Trust",
    "guard": "Trust",
    "check": "Trust",
    "preflight": "Trust",
    "verify-diff": "Trust",
    "audit": "Trust",
    "nomistakes": "Trust",
    # ── Fun ───────────────────────────────────────────────────────────────
    "whip": "Fun",
    "arena": "Fun",
    "quest": "Fun",
    "coach": "Fun",
    "leash": "Fun",
    "vibe": "Fun",
    "bounty": "Fun",
    "persona": "Fun",
    "soundboard": "Fun",
    "daily": "Fun",
    "highlight": "Fun",
    "achievements": "Fun",
    "postmortem": "Fun",
    "race": "Fun",
    "heatmap": "Fun",
    "roast": "Fun",
    "formats": "Fun",
    "flywheel": "Fun",
    "evolution": "Fun",
    # ── Integrations ──────────────────────────────────────────────────────
    "crews": "Integrations",
    "teams": "Integrations",
    "import": "Integrations",
    "llm": "Integrations",
    "sbom": "Integrations",
    "plug": "Integrations",
    "mcp": "Integrations",
    "serve": "Integrations",
    "live": "Integrations",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def group_commands(names: Iterable[str]) -> dict[str, list[str]]:
    """Group command names by category.

    Any name absent from :data:`CATEGORY_MAP` lands in ``"Other"``.  The
    returned dict always contains every key in :data:`CATEGORY_ORDER`, even
    when some categories are empty, so callers can iterate without key-existence
    checks.  Commands within each category are sorted alphabetically.

    Parameters
    ----------
    names:
        Iterable of command names (e.g. from ``_registered_names(app)``).

    Returns
    -------
    dict[str, list[str]]
        Ordered dict mapping category → sorted list of command names.

    Examples
    --------
    >>> grouped = group_commands(["setup", "swarm", "totally-new-cmd"])
    >>> grouped["Core"]
    ['setup']
    >>> grouped["Orchestrate"]
    ['swarm']
    >>> grouped["Other"]
    ['totally-new-cmd']
    """
    groups: dict[str, list[str]] = {cat: [] for cat in CATEGORY_ORDER}
    for name in names:
        cat = CATEGORY_MAP.get(name, "Other")
        groups[cat].append(name)
    for cat in groups:
        groups[cat].sort()
    return groups
