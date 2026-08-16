"""RLVR Export — your repo's verified history as a training set.

The post-training frontier converged on verifiable rewards (RLVR/GRPO):
reward only what a checker can confirm. Receipts are exactly that signal at
software-engineering grain — every episode carries an executed-verification
verdict, so the exported tuples need no learned reward model and contain no
false-greens *by construction*: an episode without a real gate verdict is
excluded, not guessed.

Output is trainer-agnostic JSONL — (prompt, trajectory, reward) — plus a
dataset digest and an in-toto attestation over it, so the provenance of the
training data is as auditable as the runs that produced it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from oh_no_my_claudecode.harness_run.attestation import Envelope, Signer, attest_receipt


@dataclass(frozen=True, slots=True)
class RlvrDataset:
    """A provenance-clean verifiable-reward dataset."""

    records: tuple[dict[str, object], ...]
    excluded: int  # episodes dropped for missing/unusable verification
    digest: str  # sha256 over canonical records

    @property
    def n_positive(self) -> int:
        return sum(1 for r in self.records if r["reward"] == 1.0)

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(r, sort_keys=True) for r in self.records)


def export_rlvr(receipts: Sequence[Mapping[str, object]], *, repo: str) -> RlvrDataset:
    """Turn run receipts into RLVR tuples; fail-closed on ambiguous episodes.

    Reward is the gate's verdict, nothing else: verified → 1.0, honestly
    failed → 0.0 (GRPO-style training needs the negatives too). An episode
    whose ``verified`` field is missing or non-boolean is *excluded* — an
    unknown verdict must never be guessed into a reward.
    """
    records: list[dict[str, object]] = []
    excluded = 0
    for receipt in receipts:
        verified = receipt.get("verified")
        goal = str(receipt.get("goal", "")).strip()
        iterations = receipt.get("iterations")
        if not isinstance(verified, bool) or not goal or not isinstance(iterations, Sequence):
            excluded += 1
            continue
        trajectory = [
            str(step.get("action_summary", ""))
            for step in iterations
            if isinstance(step, Mapping) and str(step.get("action_summary", "")).strip()
        ]
        if not trajectory:
            excluded += 1
            continue
        records.append(
            {
                "prompt": goal,
                "trajectory": trajectory,
                "reward": 1.0 if verified else 0.0,
                "repo": repo,
                "source_receipt": str(receipt.get("receipt_hash", "")),
            }
        )
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return RlvrDataset(
        records=tuple(records),
        excluded=excluded,
        digest=hashlib.sha256(canonical).hexdigest(),
    )


def attest_dataset(dataset: RlvrDataset, *, repo: str, signer: Signer | None = None) -> Envelope:
    """Seal the dataset's provenance as an in-toto/DSSE envelope.

    The predicate binds the digest, counts, and reward source ("executed
    verification") — a trainer can later prove which data a tune came from.
    """
    return attest_receipt(
        {
            "receipt_hash": dataset.digest,
            "kind": "rlvr-dataset",
            "n_records": len(dataset.records),
            "n_positive": dataset.n_positive,
            "n_excluded": dataset.excluded,
            "reward_source": "executed-verification",
        },
        repo=repo,
        tree_sha256=dataset.digest,
        signer=signer,
    )


__all__ = ["RlvrDataset", "attest_dataset", "export_rlvr"]
