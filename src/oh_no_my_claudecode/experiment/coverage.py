"""Portfolio coverage gates for ONMC external benchmark manifests.

Power planning checks whether a run is large enough. Coverage planning checks
whether the run is broad enough: enough repositories, enough task shapes, and no
single easy bucket dominating the claim.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from math import ceil, floor

__all__ = [
    "PortfolioCoverageGate",
    "PortfolioExpansionPlan",
    "gate_portfolio_coverage",
    "plan_portfolio_expansion",
]

DEFAULT_KIND_MINIMUMS: Mapping[str, int] = {
    "bugfix": 5,
    "feature": 5,
    "refactor": 3,
    "long-running": 3,
}


@dataclass(frozen=True, slots=True)
class PortfolioCoverageGate:
    """Claim-readiness gate over portfolio diversity and task metadata."""

    task_count: int
    repo_count: int
    task_kind_count: int
    task_kind_counts: tuple[tuple[str, int], ...]
    repo_counts: tuple[tuple[str, int], ...]
    required_kind_minimums: tuple[tuple[str, int], ...]
    min_repos: int
    min_task_kinds: int
    max_kind_fraction: float
    max_repo_fraction: float
    expected_outcome_count: int
    verifier_count: int
    task_kind_coverage_ready: bool
    repo_coverage_ready: bool
    balance_ready: bool
    metadata_ready: bool
    claim_ready: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "task_count": self.task_count,
            "repo_count": self.repo_count,
            "task_kind_count": self.task_kind_count,
            "task_kind_counts": dict(self.task_kind_counts),
            "repo_counts": dict(self.repo_counts),
            "required_kind_minimums": dict(self.required_kind_minimums),
            "min_repos": self.min_repos,
            "min_task_kinds": self.min_task_kinds,
            "max_kind_fraction": self.max_kind_fraction,
            "max_repo_fraction": self.max_repo_fraction,
            "expected_outcome_count": self.expected_outcome_count,
            "verifier_count": self.verifier_count,
            "task_kind_coverage_ready": self.task_kind_coverage_ready,
            "repo_coverage_ready": self.repo_coverage_ready,
            "balance_ready": self.balance_ready,
            "metadata_ready": self.metadata_ready,
            "claim_ready": self.claim_ready,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class PortfolioExpansionPlan:
    """Concrete task additions required to make a portfolio claim-sized."""

    current_tasks: int
    target_tasks: int
    minimum_total_additions: int
    kind_deficits: tuple[tuple[str, int], ...]
    suggested_minimum_additions_by_kind: tuple[tuple[str, int], ...]
    unallocated_non_dominant_additions: int
    dominant_kind: str
    dominant_kind_count: int
    max_kind_fraction: float
    dominance_only_additions_required: int
    max_additional_dominant_kind_at_target: int
    repo_deficit: int
    repo_diversity_additions_required: int
    ready_if_applied: bool
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "current_tasks": self.current_tasks,
            "target_tasks": self.target_tasks,
            "minimum_total_additions": self.minimum_total_additions,
            "kind_deficits": dict(self.kind_deficits),
            "suggested_minimum_additions_by_kind": dict(
                self.suggested_minimum_additions_by_kind
            ),
            "unallocated_non_dominant_additions": self.unallocated_non_dominant_additions,
            "dominant_kind": self.dominant_kind,
            "dominant_kind_count": self.dominant_kind_count,
            "max_kind_fraction": self.max_kind_fraction,
            "dominance_only_additions_required": self.dominance_only_additions_required,
            "max_additional_dominant_kind_at_target": self.max_additional_dominant_kind_at_target,
            "repo_deficit": self.repo_deficit,
            "repo_diversity_additions_required": self.repo_diversity_additions_required,
            "ready_if_applied": self.ready_if_applied,
            "notes": list(self.notes),
        }


def gate_portfolio_coverage(
    manifest: Mapping[str, object],
    *,
    required_kind_minimums: Mapping[str, int] = DEFAULT_KIND_MINIMUMS,
    min_repos: int = 5,
    min_task_kinds: int = 4,
    max_kind_fraction: float = 0.60,
    max_repo_fraction: float = 0.40,
) -> PortfolioCoverageGate:
    """Return a diversity and metadata gate for an external portfolio manifest."""
    if min_repos < 1:
        raise ValueError("min_repos must be positive")
    if min_task_kinds < 1:
        raise ValueError("min_task_kinds must be positive")
    if not 0 < max_kind_fraction <= 1:
        raise ValueError("max_kind_fraction must be in (0, 1]")
    if not 0 < max_repo_fraction <= 1:
        raise ValueError("max_repo_fraction must be in (0, 1]")
    normalized_minimums = {
        _non_empty_string(kind, "required_kind_minimums key"): _positive_int(
            count,
            f"required_kind_minimums[{kind!r}]",
        )
        for kind, count in required_kind_minimums.items()
    }
    tasks = _list(manifest.get("tasks"), "manifest.tasks")
    if not tasks:
        raise ValueError("manifest.tasks must not be empty")

    kind_counts: Counter[str] = Counter()
    repo_counts: Counter[str] = Counter()
    expected_outcome_count = 0
    verifier_count = 0
    for item in tasks:
        task = _mapping(item, "manifest.tasks[]")
        kind_counts[_non_empty_string(task.get("task_kind"), "manifest.tasks[].task_kind")] += 1
        repo = _mapping(task.get("repo"), "manifest.tasks[].repo")
        repo_counts[_non_empty_string(repo.get("name"), "manifest.tasks[].repo.name")] += 1
        if _is_non_empty_string(task.get("expected_outcome")):
            expected_outcome_count += 1
        verifier = task.get("verifier_argv")
        if (
            isinstance(verifier, list)
            and verifier
            and all(isinstance(arg, str) and arg for arg in verifier)
        ):
            verifier_count += 1

    task_count = len(tasks)
    reasons: list[str] = []
    task_kind_coverage_ready = len(kind_counts) >= min_task_kinds
    if not task_kind_coverage_ready:
        reasons.append(
            f"only {len(kind_counts)} task kind(s); requires at least {min_task_kinds}"
        )
    for kind, minimum in normalized_minimums.items():
        observed = kind_counts.get(kind, 0)
        if observed < minimum:
            task_kind_coverage_ready = False
            reasons.append(f"task kind {kind!r} has {observed} task(s); requires {minimum}")

    repo_coverage_ready = len(repo_counts) >= min_repos
    if not repo_coverage_ready:
        reasons.append(f"only {len(repo_counts)} repo(s); requires at least {min_repos}")

    largest_kind, largest_kind_count = kind_counts.most_common(1)[0]
    largest_repo, largest_repo_count = repo_counts.most_common(1)[0]
    largest_kind_fraction = largest_kind_count / task_count
    largest_repo_fraction = largest_repo_count / task_count
    balance_ready = True
    if largest_kind_fraction > max_kind_fraction:
        balance_ready = False
        reasons.append(
            f"task kind {largest_kind!r} is {largest_kind_fraction:.1%} of portfolio; "
            f"maximum is {max_kind_fraction:.1%}"
        )
    if largest_repo_fraction > max_repo_fraction:
        balance_ready = False
        reasons.append(
            f"repo {largest_repo!r} is {largest_repo_fraction:.1%} of portfolio; "
            f"maximum is {max_repo_fraction:.1%}"
        )

    metadata_ready = expected_outcome_count == task_count and verifier_count == task_count
    if expected_outcome_count != task_count:
        reasons.append(
            f"{task_count - expected_outcome_count} task(s) missing expected_outcome"
        )
    if verifier_count != task_count:
        reasons.append(f"{task_count - verifier_count} task(s) missing verifier_argv")

    return PortfolioCoverageGate(
        task_count=task_count,
        repo_count=len(repo_counts),
        task_kind_count=len(kind_counts),
        task_kind_counts=tuple(sorted(kind_counts.items())),
        repo_counts=tuple(sorted(repo_counts.items())),
        required_kind_minimums=tuple(sorted(normalized_minimums.items())),
        min_repos=min_repos,
        min_task_kinds=min_task_kinds,
        max_kind_fraction=max_kind_fraction,
        max_repo_fraction=max_repo_fraction,
        expected_outcome_count=expected_outcome_count,
        verifier_count=verifier_count,
        task_kind_coverage_ready=task_kind_coverage_ready,
        repo_coverage_ready=repo_coverage_ready,
        balance_ready=balance_ready,
        metadata_ready=metadata_ready,
        claim_ready=(
            task_kind_coverage_ready
            and repo_coverage_ready
            and balance_ready
            and metadata_ready
        ),
        reasons=tuple(reasons),
    )


def plan_portfolio_expansion(
    *,
    benchmark_plan: Mapping[str, object],
    coverage_gate: Mapping[str, object],
) -> PortfolioExpansionPlan:
    """Compute the minimum corpus expansion needed by power and coverage gates."""
    current_tasks = _positive_int(coverage_gate.get("task_count"), "coverage_gate.task_count")
    min_tasks_required = _positive_int(
        benchmark_plan.get("min_tasks_required"),
        "benchmark_plan.min_tasks_required",
    )
    task_kind_counts = _int_mapping(
        coverage_gate.get("task_kind_counts"),
        "coverage_gate.task_kind_counts",
    )
    repo_counts = _int_mapping(coverage_gate.get("repo_counts"), "coverage_gate.repo_counts")
    required_kind_minimums = _int_mapping(
        coverage_gate.get("required_kind_minimums"),
        "coverage_gate.required_kind_minimums",
    )
    min_repos = _positive_int(coverage_gate.get("min_repos"), "coverage_gate.min_repos")
    max_kind_fraction = _fraction(
        coverage_gate.get("max_kind_fraction"),
        "coverage_gate.max_kind_fraction",
    )
    max_repo_fraction = _fraction(
        coverage_gate.get("max_repo_fraction"),
        "coverage_gate.max_repo_fraction",
    )
    dominant_kind, dominant_kind_count = max(
        task_kind_counts.items(),
        key=lambda item: (item[1], item[0]),
    )
    largest_repo_count = max(repo_counts.values())
    kind_deficits = {
        kind: max(0, minimum - task_kind_counts.get(kind, 0))
        for kind, minimum in required_kind_minimums.items()
    }
    kind_deficits = {kind: count for kind, count in kind_deficits.items() if count}
    sample_size_deficit = max(0, min_tasks_required - current_tasks)
    dominance_additions = max(
        0,
        ceil((dominant_kind_count / max_kind_fraction) - current_tasks),
    )
    repo_deficit = max(0, min_repos - len(repo_counts))
    repo_diversity_additions = max(
        repo_deficit,
        max(0, ceil((largest_repo_count / max_repo_fraction) - current_tasks)),
    )
    minimum_total_additions = max(
        sample_size_deficit,
        sum(kind_deficits.values()),
        dominance_additions,
        repo_diversity_additions,
    )
    target_tasks = current_tasks + minimum_total_additions
    max_dominant_at_target = floor(max_kind_fraction * target_tasks)
    max_additional_dominant = max(0, max_dominant_at_target - dominant_kind_count)
    suggested = dict(kind_deficits)
    unallocated = max(0, minimum_total_additions - sum(suggested.values()))
    notes = [
        "Prefer assigning unallocated tasks to non-dominant task kinds until the "
        "fresh report proves those classes are discriminative.",
        f"At the {target_tasks}-task target, no more than {max_additional_dominant} "
        f"additional {dominant_kind!r} task(s) should be added.",
    ]
    if repo_deficit:
        notes.append(
            f"Introduce at least {repo_deficit} new repo(s) while adding the next tasks."
        )
    if repo_diversity_additions > repo_deficit:
        notes.append(
            "Place new tasks outside the current largest repo bucket to satisfy repo balance."
        )

    return PortfolioExpansionPlan(
        current_tasks=current_tasks,
        target_tasks=target_tasks,
        minimum_total_additions=minimum_total_additions,
        kind_deficits=tuple(sorted(kind_deficits.items())),
        suggested_minimum_additions_by_kind=tuple(sorted(suggested.items())),
        unallocated_non_dominant_additions=unallocated,
        dominant_kind=dominant_kind,
        dominant_kind_count=dominant_kind_count,
        max_kind_fraction=max_kind_fraction,
        dominance_only_additions_required=dominance_additions,
        max_additional_dominant_kind_at_target=max_additional_dominant,
        repo_deficit=repo_deficit,
        repo_diversity_additions_required=repo_diversity_additions,
        ready_if_applied=minimum_total_additions == 0,
        notes=tuple(notes),
    )


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    return value


def _non_empty_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_int(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _int_mapping(value: object, path: str) -> dict[str, int]:
    mapping = _mapping(value, path)
    result: dict[str, int] = {}
    for key, count in mapping.items():
        result[_non_empty_string(key, f"{path} key")] = _positive_int(
            count,
            f"{path}[{key!r}]",
        )
    return result


def _fraction(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 1:
        raise ValueError(f"{path} must be in (0, 1]")
    return float(value)
