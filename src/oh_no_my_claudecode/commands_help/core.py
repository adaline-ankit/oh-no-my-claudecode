"""Pure-logic helpers for ``onmc commands`` help tiering and product surface.

Separated from the Typer surface so they can be tested without importing the
CLI or registering any commands.  The only external dependency is stdlib.

Design
------
- ``PRIMARY_WORKFLOW_COMMANDS``: the small user-facing product surface.  The
  large command catalog remains callable, but primary help must stay focused on
  the runtime workflow described in the SOTA plan.
- ``CATEGORY_MAP``: maintained dict ``command-name → category``.  Any command
  name absent from the map automatically lands in ``"Other"``, so new commands
  added to the app remain discoverable without a forced update here.
- ``group_commands(names)``: pure function; deterministic (sorted within each
  category); returns the full set of categories even when some are empty so
  callers can iterate without key-existence checks.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

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
# Product surface — shown in root help and treated as the primary workflow
# ---------------------------------------------------------------------------

PRIMARY_COMMAND_LIMIT = 14

PRIMARY_WORKFLOW_COMMANDS: tuple[str, ...] = (
    "run",
    "setup",
    "init",
    "quickstart",
    "brief",
    "guard",
    "recall",
    "status",
    "mission",
    "missioncontrol",
    "ui",
    "wrap",
    "serve",
    "commands",
)

CORE_COMMANDS: list[str] = list(PRIMARY_WORKFLOW_COMMANDS)
"""Backward-compatible alias for tests and users of the older help tier."""

PRIMARY_COMMAND_ROLES: dict[str, str] = {
    "setup": "one-time install and hook setup",
    "init": "repo-local project bootstrap",
    "quickstart": "first-run guided bootstrap",
    "run": "canonical verified runtime entry point",
    "mission": "plan and progress view over the runtime contract",
    "missioncontrol": "observed run, evidence, and worker state",
    "ui": "local Mission Control UI",
    "wrap": "Claude Code hook integration for the same runtime contract",
    "serve": "local service surface for UI and integrations",
    "status": "repo and ONMC health summary",
    "brief": "context briefing before a run",
    "guard": "policy and safety context",
    "recall": "measured memory/context recall",
    "commands": "advanced catalog browser",
}

# ---------------------------------------------------------------------------
# Category map — command-name → category
# ---------------------------------------------------------------------------
# Anything not listed here falls through to "Other" automatically.
# "quickstart" is reserved so it lands in Core once that branch merges.

CATEGORY_MAP: dict[str, str] = {
    # ── Core ─────────────────────────────────────────────────────────────
    "run": "Core",
    "setup": "Core",
    "quickstart": "Core",
    "wrap": "Core",
    "brief": "Core",
    "guard": "Core",
    "recall": "Core",
    "ui": "Core",
    "init": "Core",
    "serve": "Core",
    "status": "Core",
    "commands": "Core",
    "mission": "Core",
    "missioncontrol": "Core",
    # ── Orchestrate ───────────────────────────────────────────────────────
    "autopilot": "Orchestrate",
    "swarm": "Orchestrate",
    "refinery": "Orchestrate",
    "land": "Orchestrate",
    "nightshift": "Orchestrate",
    "loop": "Orchestrate",
    "loop-templates": "Orchestrate",
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
    "live": "Integrations",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandSurfaceAudit:
    """Auditable shape of the user-facing command surface.

    This is intentionally stricter than category grouping: it answers whether
    the live CLI still presents ONMC as one runtime with advanced operator tools
    behind it, instead of drifting back into a 100-command product surface.
    """

    total_commands: int
    primary_limit: int
    expected_primary: tuple[str, ...]
    visible_primary: tuple[str, ...]
    hidden_advanced_count: int
    missing_primary: tuple[str, ...]
    hidden_primary: tuple[str, ...]
    unexpected_visible: tuple[str, ...]

    @property
    def primary_limit_ok(self) -> bool:
        return len(self.visible_primary) <= self.primary_limit

    @property
    def ready(self) -> bool:
        return (
            self.primary_limit_ok
            and not self.missing_primary
            and not self.hidden_primary
            and not self.unexpected_visible
            and "run" in self.visible_primary
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "total_commands": self.total_commands,
            "primary_limit": self.primary_limit,
            "primary_limit_ok": self.primary_limit_ok,
            "expected_primary": list(self.expected_primary),
            "visible_primary": list(self.visible_primary),
            "hidden_advanced_count": self.hidden_advanced_count,
            "missing_primary": list(self.missing_primary),
            "hidden_primary": list(self.hidden_primary),
            "unexpected_visible": list(self.unexpected_visible),
            "canonical_entrypoint": "run",
            "advanced_catalog": "commands --all",
            "roles": dict(PRIMARY_COMMAND_ROLES),
        }


def audit_command_surface(
    names: Iterable[str],
    visible_names: Iterable[str],
    *,
    primary_limit: int = PRIMARY_COMMAND_LIMIT,
) -> CommandSurfaceAudit:
    """Return the product-surface audit for a live command registry."""
    live = set(names)
    visible = set(visible_names)
    expected = tuple(PRIMARY_WORKFLOW_COMMANDS)
    expected_set = set(expected)
    visible_primary = tuple(sorted(visible & expected_set))
    hidden_advanced = live - expected_set - visible
    return CommandSurfaceAudit(
        total_commands=len(live),
        primary_limit=primary_limit,
        expected_primary=expected,
        visible_primary=visible_primary,
        hidden_advanced_count=len(hidden_advanced),
        missing_primary=tuple(sorted(expected_set - live)),
        hidden_primary=tuple(sorted((expected_set & live) - visible)),
        unexpected_visible=tuple(sorted(visible - expected_set)),
    )


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
