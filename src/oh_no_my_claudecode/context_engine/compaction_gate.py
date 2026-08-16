"""R1 — verified compaction: prove what survived before trusting a summary.

The named open problem ("Governance Decay") is that context compaction
*silently erases safety constraints* in long-horizon agents: the summary reads
fine, the invariant is gone, and nothing notices until the agent violates it.
Every production compactor today — threshold summarizers, trained pruning,
condenser pipelines — is unverified.

This gate makes compaction fail-closed: the caller declares the load-bearing
constraints (policies, invariants, the task contract), and a proposed
compaction is ACCEPTED only if every constraint that held in the full context
still holds in the compacted one. Rejection names exactly what was lost, so a
compactor can repair (re-inject the lost constraints) and retry.

View-level by design (the OpenHands condenser insight): the gate never mutates
anything — the full context remains the source of truth; compaction only ever
produces a view, and this module only ever judges it.

The measurement half of R1 — scoring compaction *policies* by benchmark lift
per token freed — runs through the experiment kernel; this module is the
correctness half.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class ConstraintKind(StrEnum):
    """How a constraint is checked for survival."""

    LITERAL = "literal"  # case-insensitive substring
    REGEX = "regex"  # re.search


@dataclass(frozen=True, slots=True)
class Constraint:
    """One load-bearing fact that must survive every compaction."""

    constraint_id: str
    pattern: str
    kind: ConstraintKind = ConstraintKind.LITERAL

    def __post_init__(self) -> None:
        if not self.constraint_id.strip():
            raise ValueError("constraint_id must not be empty")
        if not self.pattern.strip():
            raise ValueError("pattern must not be empty")
        if self.kind is ConstraintKind.REGEX:
            re.compile(self.pattern)  # invalid regex fails at declaration, not at check

    def holds_in(self, text: str) -> bool:
        if self.kind is ConstraintKind.REGEX:
            return re.search(self.pattern, text, re.IGNORECASE) is not None
        return self.pattern.lower() in text.lower()


@dataclass(frozen=True, slots=True)
class CompactionVerdict:
    """The gate's judgment of one proposed compaction."""

    accepted: bool
    lost: tuple[str, ...]  # constraint ids present before, absent after
    checked: int
    tokens_before: int
    tokens_after: int

    @property
    def tokens_freed(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "lost": list(self.lost),
            "checked": self.checked,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_freed": self.tokens_freed,
        }


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def check_compaction(
    before: str,
    after: str,
    constraints: Sequence[Constraint],
) -> CompactionVerdict:
    """Judge a proposed compaction: fail-closed on any lost constraint.

    A constraint counts only when it *held in the full context* — the gate
    verifies preservation, it does not invent obligations the context never
    carried. Deterministic, offline, no LLM.
    """
    active = [c for c in constraints if c.holds_in(before)]
    lost = tuple(c.constraint_id for c in active if not c.holds_in(after))
    return CompactionVerdict(
        accepted=not lost,
        lost=lost,
        checked=len(active),
        tokens_before=_estimate_tokens(before),
        tokens_after=_estimate_tokens(after),
    )


def repair_compaction(
    after: str,
    before: str,
    verdict: CompactionVerdict,
    constraints: Sequence[Constraint],
) -> str:
    """Re-inject lost constraints verbatim so a rejected compaction can pass.

    The repair appends the *original* lines that satisfied each lost
    constraint (never a paraphrase — paraphrase is how decay starts). For
    regex constraints the first matching line from the full context is used.
    """
    if verdict.accepted:
        return after
    by_id = {c.constraint_id: c for c in constraints}
    preserved: list[str] = []
    before_lines = before.splitlines()
    for constraint_id in verdict.lost:
        constraint = by_id[constraint_id]
        line = next((ln for ln in before_lines if constraint.holds_in(ln)), constraint.pattern)
        preserved.append(line.strip())
    block = "\n".join(dict.fromkeys(preserved))
    return f"{after}\n\n<preserved-constraints>\n{block}\n</preserved-constraints>"


__all__ = [
    "CompactionVerdict",
    "Constraint",
    "ConstraintKind",
    "check_compaction",
    "repair_compaction",
]
