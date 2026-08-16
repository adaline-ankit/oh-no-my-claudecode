"""M6 — measured forgetting: the attribution ledger drives retirement.

The missing half of the earned-memory loop. Attribution produces verdicts;
this module acts on them: every HARMFUL artifact that was actually ingested is
rolled back through the gate (which also removes it from the sink), and the
outcome is reported honestly — retired, not-found, or failed. Memories the
gate never admitted can't be retired (there is nothing to remove); that is
reported rather than hidden.

One call closes the loop:

    ledger = attribute_memories(...)
    report = retire_harmful(ledger, ingestor)

Poisoning defense in depth, final layer: sanitizer (write time) → shadow eval
(promotion time) → attribution (measured, after the fact) → THIS (removal).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from oh_no_my_claudecode.learning.attribution import MemoryLift, retirement_candidates
from oh_no_my_claudecode.learning.ingest import GatedIngestor


@dataclass(frozen=True, slots=True)
class RetirementReport:
    """What measured forgetting actually did — no silent outcomes."""

    retired: tuple[str, ...]
    not_ingested: tuple[str, ...]  # HARMFUL but never admitted; nothing to remove
    failed: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "retired": list(self.retired),
            "not_ingested": list(self.not_ingested),
            "failed": list(self.failed),
        }


def retire_harmful(
    ledger: Sequence[MemoryLift],
    ingestor: GatedIngestor,
    *,
    reason: str = "attribution: measured harmful lift",
) -> RetirementReport:
    """Roll back every HARMFUL artifact the ingestor admitted.

    Uses :func:`retirement_candidates` (CI-backed HARMFUL verdicts only —
    unproven artifacts are never retired on a hunch). Idempotent: a second
    call finds nothing left to remove.
    """
    retired: list[str] = []
    not_ingested: list[str] = []
    failed: list[str] = []
    for memory_id in retirement_candidates(ledger):
        result = ingestor.rollback(memory_id, reason=reason)
        if result.rolled_back:
            retired.append(memory_id)
        elif "unknown memory id" in result.reason:
            not_ingested.append(memory_id)
        else:
            failed.append(memory_id)
    return RetirementReport(tuple(retired), tuple(not_ingested), tuple(failed))


__all__ = ["RetirementReport", "retire_harmful"]
