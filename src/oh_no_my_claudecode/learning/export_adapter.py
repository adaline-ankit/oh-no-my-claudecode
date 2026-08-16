"""M9 — export earned memories to external stores; be the filter, not the store.

Memory hubs (mem0, Zep, team memory stores) ingest everything and verify
nothing. This adapter is the one-way valve in front of them: only memories the
gate promoted AND the ledger does not condemn flow out, and every exported
record carries its evidence inline — so the receiving store holds *earned*
knowledge with its provenance, not vibes.

Pure function → portable dicts (mem0's add() shape: ``memory`` text +
``metadata``). The consumer posts them with whatever client it already has;
no HTTP or vendor dependency here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from oh_no_my_claudecode.learning.attribution import LiftVerdict, MemoryLift


@dataclass(frozen=True, slots=True)
class ExportBatch:
    """What left the gate — and what was refused, by name."""

    records: tuple[dict[str, object], ...]
    refused: tuple[tuple[str, str], ...]  # (memory_id, reason)

    def to_dict(self) -> dict[str, object]:
        return {
            "records": [dict(r) for r in self.records],
            "refused": [{"memory_id": m, "reason": r} for m, r in self.refused],
        }


def to_export_records(
    memories: Mapping[str, str],
    ledger: Sequence[MemoryLift],
) -> ExportBatch:
    """Filter promoted memories through the ledger and shape them for export.

    Rules (the PRD gate: "ledger-approved memories flow out, unapproved never"):
    - HARMFUL → refused, always.
    - No ledger entry → refused ("unmeasured") — exporting unmeasured memories
      would launder them into a store that can't tell.
    - EARNING / UNPROVEN-with-nonnegative-mean → exported with evidence inline.
    """
    by_id = {entry.memory_id: entry for entry in ledger}
    records: list[dict[str, object]] = []
    refused: list[tuple[str, str]] = []
    for memory_id, content in sorted(memories.items()):
        entry = by_id.get(memory_id)
        if entry is None:
            refused.append((memory_id, "unmeasured: no attribution ledger entry"))
            continue
        if entry.verdict is LiftVerdict.HARMFUL:
            refused.append((memory_id, "harmful: measured negative lift"))
            continue
        if entry.mean_lift < 0:
            refused.append((memory_id, "negative-mean: not condemned, but not exportable"))
            continue
        records.append(
            {
                "memory": content,
                "metadata": {
                    "onmc_memory_id": memory_id,
                    "onmc_verdict": entry.verdict.value,
                    "onmc_lift_mean": entry.mean_lift,
                    "onmc_lift_ci95": list(entry.ci95),
                    "onmc_n_tasks": entry.n_tasks,
                },
            }
        )
    return ExportBatch(tuple(records), tuple(refused))


__all__ = ["ExportBatch", "to_export_records"]
