"""Intake normalizer for the mission bridge.

Turns an inbound chat message (e.g. ``"@onmc refactor the auth layer with 4
agents"``) into a structured
:class:`~oh_no_my_claudecode.missionbridge.models.IntakeTask` — the mission goal
plus any inline options (concurrency / budget).

Pure, deterministic, offline: no I/O, no clock, no network.  A live gateway
strips its own transport envelope, then hands the raw user text here.

Recognised shapes::

    @onmc <goal>                     # Slack-style mention
    /onmc <goal>                     # slash command
    onmc: <goal>                     # prefix command

    --concurrency 4 | conc=4 | with 4 agents   -> concurrency
    --budget-usd 3  | budget $3     | cap $3    -> budget_usd

Option tokens are stripped out of the returned goal; the remainder is the
cleaned free-text goal.  A message with no goal after stripping (empty or
mention-only) yields ``None``.
"""

from __future__ import annotations

import re

from oh_no_my_claudecode.missionbridge.models import IntakeTask

__all__ = ["parse_intake"]


# Separators that may sit between a bot mention/command and the goal.
_SEP = " \t\r\n:"

# Inline concurrency options: "--concurrency 4", "conc=4", "with 4 agents".
_CONCURRENCY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"--concurrency[=\s]+(\d+)", re.IGNORECASE),
    re.compile(r"\bconc=(\d+)", re.IGNORECASE),
    re.compile(r"\bwith\s+(\d+)\s+agents?\b", re.IGNORECASE),
)

# Inline budget options: "--budget-usd 3", "budget $3", "cap $3".
_BUDGET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"--budget-usd[=\s]+(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"\bbudget\s+\$?(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"\bcap\s+\$?(\d+(?:\.\d+)?)", re.IGNORECASE),
)


def parse_intake(message: str, *, mention: str = "@onmc") -> IntakeTask | None:
    """Normalize a chat *message* into an :class:`IntakeTask`.

    Parameters
    ----------
    message:
        Raw user text (transport envelope already removed by the gateway).
    mention:
        The bot handle to strip when it leads the message.  ``"@onmc"`` also
        covers the ``/onmc`` and ``onmc:`` command forms (derived from the bare
        name).

    Returns
    -------
    IntakeTask | None
        The parsed task, or ``None`` when there is no goal left after stripping
        the mention and option tokens.
    """
    if not message:
        return None
    text = message.strip()
    if not text:
        return None

    remainder = _strip_mention(text, mention)
    concurrency, budget_usd, goal = _extract_options(remainder)
    goal = goal.strip()
    if not goal:
        return None
    return IntakeTask(goal=goal, concurrency=concurrency, budget_usd=budget_usd)


def _strip_mention(text: str, mention: str) -> str:
    """Remove a single leading ``@name`` / ``/name`` / bare-``name`` prefix."""
    name = mention.lstrip("@/").rstrip(":").strip()
    if not name:
        return text
    lowered = text.lower()
    for prefix in (f"@{name}", f"/{name}", name):
        if lowered.startswith(prefix.lower()):
            rest = text[len(prefix) :]
            # Only treat it as a prefix when a separator (or end) follows, so
            # "onmcify" is never mistaken for the bare "onmc" handle.
            if rest == "" or not (rest[0].isalnum() or rest[0] == "_"):
                return rest.lstrip(_SEP)
    return text


def _extract_options(goal: str) -> tuple[int | None, float | None, str]:
    """Pull inline concurrency/budget options and return them with clean text.

    The earliest match (by position) wins per category; every matched option
    token is removed from the returned goal.
    """
    spans: list[tuple[int, int]] = []

    conc_hits: list[tuple[int, int, int]] = []
    for pattern in _CONCURRENCY_PATTERNS:
        for match in pattern.finditer(goal):
            conc_hits.append((match.start(), match.end(), int(match.group(1))))
    concurrency: int | None = None
    if conc_hits:
        conc_hits.sort()
        concurrency = conc_hits[0][2]
        spans.extend((start, end) for start, end, _ in conc_hits)

    budget_hits: list[tuple[int, int, float]] = []
    for pattern in _BUDGET_PATTERNS:
        for match in pattern.finditer(goal):
            budget_hits.append((match.start(), match.end(), float(match.group(1))))
    budget_usd: float | None = None
    if budget_hits:
        budget_hits.sort()
        budget_usd = budget_hits[0][2]
        spans.extend((start, end) for start, end, _ in budget_hits)

    return concurrency, budget_usd, _remove_spans(goal, spans)


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Delete *spans* from *text* and collapse surrounding whitespace."""
    if not spans:
        return _normalize_ws(text)
    pieces: list[str] = []
    cursor = 0
    for start, end in _merge_spans(sorted(spans)):
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return _normalize_ws("".join(pieces))


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping/adjacent ``(start, end)`` spans (already sorted)."""
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _normalize_ws(text: str) -> str:
    """Collapse runs of whitespace to single spaces and strip the ends."""
    return " ".join(text.split())
