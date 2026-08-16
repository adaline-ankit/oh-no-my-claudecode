"""R2 — procedural distillation: verified trajectories → workflow candidates.

The memory literature calls procedural memory the least-developed,
highest-impact tier, and names its missing piece: an objective function. This
module supplies the pipeline's front half — mine recurring multi-step
workflows from *verified* run receipts (proof-first: unverified trajectories
never teach) — and emits gate-ready :class:`~.models.LearningCandidate`
skills. The back half already exists: the promotion gate screens them and
attribution measures each one's lift on the repo's own benchmark, so a
distilled workflow is promoted, retired, or rejected by evidence.

Deterministic and offline by design: normalization + frequent-subsequence
mining, no LLM calls. An LLM-polish pass is an optional later stage — the
objective function is the contribution, not the prose.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from oh_no_my_claudecode.learning.models import (
    CandidateKind,
    LearningCandidate,
    Provenance,
    Scope,
)

#: Specifics scrubbed during normalization so "edit src/a.py" and
#: "edit lib/b.py" mine as the same procedural step.
_PATH_RE = re.compile(r"[\w./-]+\.(?:py|ts|js|rs|go|java|md|toml|yaml|yml|json)\b")
_NUM_RE = re.compile(r"\b\d+\b")
_WS_RE = re.compile(r"\s+")

#: Steps this generic carry no procedure; drop before mining.
_NOISE_STEPS = frozenset({"", "n/a", "none", "continue", "done"})


def normalize_step(action_summary: str) -> str:
    """Collapse one action summary to its procedural signature."""
    step = action_summary.strip().lower()
    step = _PATH_RE.sub("<file>", step)
    step = _NUM_RE.sub("<n>", step)
    step = _WS_RE.sub(" ", step)
    return step


def _trace(receipt: Mapping[str, object]) -> list[str]:
    iterations = receipt.get("iterations")
    if not isinstance(iterations, Sequence):
        return []
    steps: list[str] = []
    for iteration in iterations:
        if not isinstance(iteration, Mapping):
            continue
        step = normalize_step(str(iteration.get("action_summary", "")))
        if step in _NOISE_STEPS:
            continue
        if steps and steps[-1] == step:
            continue  # collapse immediate repeats (retry storms are not procedure)
        steps.append(step)
    return steps


@dataclass(frozen=True, slots=True)
class WorkflowCandidate:
    """One mined procedural workflow with its support evidence."""

    workflow_id: str
    steps: tuple[str, ...]
    support: tuple[str, ...]  # receipt hashes/ids of the verified runs behind it

    def render(self) -> str:
        lines = [
            f"Learned workflow (support: {len(self.support)} verified runs):",
            *[f"{index}. {step}" for index, step in enumerate(self.steps, start=1)],
        ]
        return "\n".join(lines)

    def to_learning_candidate(self, *, repo: str = "") -> LearningCandidate:
        """Gate-ready skill candidate; state starts at OBSERVED, as required."""
        return LearningCandidate(
            id=f"wf-{self.workflow_id}",
            kind=CandidateKind.SKILL,
            content=self.render(),
            provenance=Provenance(trace_ids=self.support),
            scope=Scope(repos=(repo,) if repo else ()),
        )


def distill_workflows(
    receipts: Sequence[Mapping[str, object]],
    *,
    min_support: int = 2,
    min_len: int = 2,
    max_len: int = 6,
) -> list[WorkflowCandidate]:
    """Mine recurring step subsequences across VERIFIED receipts only.

    Contiguous n-gram mining (length ``min_len..max_len``) with per-receipt
    support counting; maximal sequences suppress their equal-support
    subsequences so one long workflow doesn't spawn its own fragments.
    Deterministic: output sorted by (support desc, length desc, id).
    """
    traces: dict[str, list[str]] = {}
    for receipt in receipts:
        if not receipt.get("verified"):
            continue  # proof-first: unverified runs never teach
        receipt_id = str(receipt.get("receipt_hash") or receipt.get("goal") or id(receipt))
        steps = _trace(receipt)
        if len(steps) >= min_len:
            traces[receipt_id] = steps

    support: dict[tuple[str, ...], set[str]] = {}
    for receipt_id, steps in traces.items():
        seen: set[tuple[str, ...]] = set()
        for length in range(min_len, min(max_len, len(steps)) + 1):
            for start in range(len(steps) - length + 1):
                gram = tuple(steps[start : start + length])
                if gram not in seen:  # count once per receipt
                    seen.add(gram)
                    support.setdefault(gram, set()).add(receipt_id)

    frequent = {gram: ids for gram, ids in support.items() if len(ids) >= min_support}

    def _contains(longer: tuple[str, ...], shorter: tuple[str, ...]) -> bool:
        return any(
            longer[offset : offset + len(shorter)] == shorter
            for offset in range(len(longer) - len(shorter) + 1)
        )

    maximal: list[tuple[str, ...]] = []
    for gram in sorted(frequent, key=len, reverse=True):
        if any(_contains(kept, gram) and frequent[kept] >= frequent[gram] for kept in maximal):
            continue
        maximal.append(gram)

    candidates = [
        WorkflowCandidate(
            workflow_id=hashlib.sha256("\x1f".join(gram).encode()).hexdigest()[:16],
            steps=gram,
            support=tuple(sorted(frequent[gram])),
        )
        for gram in maximal
    ]
    candidates.sort(key=lambda c: (-len(c.support), -len(c.steps), c.workflow_id))
    return candidates


__all__ = ["WorkflowCandidate", "distill_workflows", "normalize_step"]
