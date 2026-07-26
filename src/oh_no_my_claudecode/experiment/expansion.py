"""Draft task-slot generation for expanding external benchmark portfolios.

This module does not create live benchmark tasks. A live task still needs a real
upstream mutation, verifier, vacuity check, and corpus-integrity coverage. The
draft is the authoring queue that turns a failed gap plan into concrete slots to
fill next.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from oh_no_my_claudecode.experiment.coverage import plan_portfolio_expansion

__all__ = [
    "DraftTaskSlot",
    "PortfolioExpansionDraft",
    "build_portfolio_expansion_draft",
]


@dataclass(frozen=True, slots=True)
class DraftTaskSlot:
    """One planned task slot that still needs a real mutation/verifier."""

    slot_id: str
    task_kind: str
    suggested_repo: str
    required_by: str
    rationale: str

    def to_dict(self) -> dict[str, object]:
        return {
            "slot_id": self.slot_id,
            "task_kind": self.task_kind,
            "suggested_repo": self.suggested_repo,
            "required_by": self.required_by,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class PortfolioExpansionDraft:
    """Concrete draft queue for making a portfolio claim-sized."""

    base_task_count: int
    target_task_count: int
    slot_count: int
    dominant_kind: str
    max_additional_dominant_kind_at_target: int
    slots_by_kind: tuple[tuple[str, int], ...]
    slots_by_repo: tuple[tuple[str, int], ...]
    slots: tuple[DraftTaskSlot, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "base_task_count": self.base_task_count,
            "target_task_count": self.target_task_count,
            "slot_count": self.slot_count,
            "dominant_kind": self.dominant_kind,
            "max_additional_dominant_kind_at_target": (
                self.max_additional_dominant_kind_at_target
            ),
            "slots_by_kind": dict(self.slots_by_kind),
            "slots_by_repo": dict(self.slots_by_repo),
            "slots": [slot.to_dict() for slot in self.slots],
            "notes": list(self.notes),
        }


def build_portfolio_expansion_draft(
    *,
    manifest: Mapping[str, object],
    benchmark_plan: Mapping[str, object],
    coverage_gate: Mapping[str, object],
    slot_prefix: str = "planned-v5",
) -> PortfolioExpansionDraft:
    """Build deterministic planned task slots from a gap plan."""
    tasks = _list(manifest.get("tasks"), "manifest.tasks")
    gap = plan_portfolio_expansion(
        benchmark_plan=benchmark_plan,
        coverage_gate=coverage_gate,
    )
    kind_counts = _int_mapping(coverage_gate.get("task_kind_counts"), "task_kind_counts")
    repo_counts = _int_mapping(coverage_gate.get("repo_counts"), "repo_counts")
    additions = dict(gap.suggested_minimum_additions_by_kind)
    eligible_kinds = sorted(kind for kind in kind_counts if kind != gap.dominant_kind)
    if not eligible_kinds:
        eligible_kinds = sorted(kind_counts)
    projected_kind_counts = Counter(kind_counts)
    for kind, count in additions.items():
        projected_kind_counts[kind] += count
    for _ in range(gap.unallocated_non_dominant_additions):
        kind = min(
            eligible_kinds,
            key=lambda item: (projected_kind_counts[item], item),
        )
        additions[kind] = additions.get(kind, 0) + 1
        projected_kind_counts[kind] += 1

    projected_repo_counts = Counter(repo_counts)
    slots: list[DraftTaskSlot] = []
    kind_ordinals: Counter[str] = Counter()
    for kind, count in sorted(additions.items()):
        for _ in range(count):
            kind_ordinals[kind] += 1
            repo = min(
                projected_repo_counts,
                key=lambda item: (projected_repo_counts[item], item),
            )
            projected_repo_counts[repo] += 1
            required_by = (
                "kind-minimum"
                if kind_ordinals[kind] <= dict(gap.kind_deficits).get(kind, 0)
                else "sample-size-and-balance"
            )
            slots.append(
                DraftTaskSlot(
                    slot_id=f"{slot_prefix}-{_slug(kind)}-{kind_ordinals[kind]:02d}",
                    task_kind=kind,
                    suggested_repo=repo,
                    required_by=required_by,
                    rationale=(
                        "Fill with a real upstream mutation and verifier; do not "
                        "promote to a live manifest task until pristine/failing/fixed "
                        "validity gates pass."
                    ),
                )
            )

    return PortfolioExpansionDraft(
        base_task_count=len(tasks),
        target_task_count=gap.target_tasks,
        slot_count=len(slots),
        dominant_kind=gap.dominant_kind,
        max_additional_dominant_kind_at_target=(
            gap.max_additional_dominant_kind_at_target
        ),
        slots_by_kind=tuple(sorted(Counter(slot.task_kind for slot in slots).items())),
        slots_by_repo=tuple(sorted(Counter(slot.suggested_repo for slot in slots).items())),
        slots=tuple(slots),
        notes=(
            "Draft slots are not benchmark tasks. Each slot must become a real "
            "manifest task with a mutation table entry and passing corpus-integrity tests.",
            *gap.notes,
        ),
    )


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    return value


def _int_mapping(value: object, path: str) -> dict[str, int]:
    mapping = _mapping(value, path)
    result: dict[str, int] = {}
    for key, raw_count in mapping.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"{path} key must be a non-empty string")
        if not isinstance(raw_count, int) or isinstance(raw_count, bool) or raw_count < 1:
            raise ValueError(f"{path}[{key!r}] must be a positive integer")
        result[key] = raw_count
    return result


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value.lower()).strip("-")
