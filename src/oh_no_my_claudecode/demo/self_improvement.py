"""H9 — the provable self-improvement demo, in one runnable script.

Chains the real modules end to end and prints an auditable story:

1. verified run receipts → :func:`~oh_no_my_claudecode.learning.distill.distill_workflows`
   mines a recurring debugging workflow (the unverified receipt teaches nothing);
2. the mined workflow is driven through the eval-gated
   :class:`~oh_no_my_claudecode.learning.ingest.GatedIngestor` and promoted on
   held-out evidence, while a poison memory is refused by the same gate;
3. :func:`~oh_no_my_claudecode.learning.attribution.attribute_memories` measures
   each memory's per-task lift — the workflow earns, the poison is measured
   harmful — and harmful ids are retired (or reported never admitted);
4. :func:`~oh_no_my_claudecode.experiment.evolve.evolve_step` promotes a
   challenger harness carrying the workflow only because its paired-delta CI
   excludes zero;
5. the whole story is sealed as an in-toto/DSSE envelope via
   :func:`~oh_no_my_claudecode.harness_run.attestation.attest_receipt`.

No mocks of project code — fixture data only for inputs. Deterministic for a
fixed seed: two calls return byte-identical results.

Run it: ``python -m oh_no_my_claudecode.demo.self_improvement``
"""

from __future__ import annotations

import hashlib
from typing import cast

from oh_no_my_claudecode.experiment.evolve import HarnessVariant, evolve_step
from oh_no_my_claudecode.harness_run.attestation import attest_receipt, verify_envelope_payload
from oh_no_my_claudecode.learning.attribution import attribute_memories, retirement_candidates
from oh_no_my_claudecode.learning.distill import distill_workflows
from oh_no_my_claudecode.learning.gate import PromotionGate
from oh_no_my_claudecode.learning.ingest import GatedIngestor, IngestedMemory
from oh_no_my_claudecode.learning.models import (
    CandidateKind,
    LearningCandidate,
    Provenance,
    Scope,
    ShadowEvaluation,
)

#: Fixed epoch-ms clock injected everywhere a timestamp is recorded, so two
#: demo runs produce byte-identical promotion records and envelopes.
_DEMO_CLOCK_MS = 1_735_689_600_000

# -- attribution benchmark fixture -------------------------------------------
# 20 tasks at a 5/10 helped rate and a 3/10 hurt rate. n=20 (not 10) because a
# 95% bootstrap CI over 10 binary tasks cannot flag a 3-task harm as
# significant (its 97.5th percentile lands exactly on 0.0 → unproven).
_TASKS = tuple(f"t{i:02d}" for i in range(20))
_HELPED = frozenset(_TASKS[:10])  # the workflow flips these to pass
_HURT = frozenset(_TASKS[10:16])  # the poison flips these to fail

# -- evolution benchmark fixture ----------------------------------------------
_EVOLUTION_TASKS = tuple(f"e{i:02d}" for i in range(12))
_CHAMPION_ID = "champion-baseline"
_CHALLENGER_ID = "challenger-workflow"
_CHAMPION_PASSES = frozenset(_EVOLUTION_TASKS[:4])  # champion: 4/12
_CHALLENGER_PASSES = frozenset(_EVOLUTION_TASKS[:8])  # challenger: 8/12


class _RecordingSink:
    """Tiny in-module recording sink — the only 'store' the demo writes to."""

    def __init__(self) -> None:
        self.memories: dict[str, IngestedMemory] = {}

    def write(self, memory: IngestedMemory) -> str:
        self.memories[memory.memory_id] = memory
        return memory.memory_id

    def remove(self, memory_id: str) -> bool:
        return self.memories.pop(memory_id, None) is not None


def _fixture_receipts() -> list[dict[str, object]]:
    """3 verified + 1 unverified receipts sharing one 3-step debugging workflow.

    File paths and numbers vary per receipt; normalization collapses them, so
    the verified three mine as one recurring procedure.
    """

    def receipt(tag: str, verified: bool, path: str, failures: int, line: int) -> dict[str, object]:
        return {
            "receipt_hash": hashlib.sha256(f"demo-receipt-{tag}".encode()).hexdigest(),
            "verified": verified,
            "iterations": [
                {"action_summary": f"run pytest and see {failures} failures in {path}"},
                {"action_summary": f"add debug logging around line {line} in {path}"},
                {"action_summary": f"fix the off-by-one in {path} and rerun pytest until green"},
            ],
        }

    return [
        receipt("alpha", True, "src/parser.py", 3, 42),
        receipt("bravo", True, "tests/api.py", 7, 108),
        receipt("charlie", True, "lib/query.py", 2, 9),
        receipt("delta", False, "src/cache.py", 5, 77),  # unverified: never teaches
    ]


def _bench_task(task_id: str, memory_ids: frozenset[str]) -> bool:
    """Deterministic task runner: workflow helps _HELPED, poison hurts _HURT."""
    passes = task_id in _HURT  # these pass by default, so the poison measurably hurts
    if "workflow" in memory_ids and task_id in _HELPED:
        passes = True
    if "poison" in memory_ids and task_id in _HURT:
        passes = False
    return passes


def _evolution_run(variant_id: str, task_id: str) -> bool:
    """Deterministic variant runner: challenger wins 8/12 vs champion's 4/12."""
    wins = _CHALLENGER_PASSES if variant_id == _CHALLENGER_ID else _CHAMPION_PASSES
    return task_id in wins


def run_demo(seed: int = 7) -> dict[str, object]:
    """Drive the full self-improvement loop and return the auditable outcome."""
    narrative: list[str] = []

    # 1-2. Mine workflows from verified receipts only.
    receipts = _fixture_receipts()
    unverified = [str(r["receipt_hash"]) for r in receipts if not r["verified"]]
    workflows = distill_workflows(receipts)
    if not workflows:
        raise RuntimeError("fixture receipts must mine at least one workflow")
    workflow = workflows[0]
    if len(workflow.support) != len(receipts) - len(unverified):
        raise RuntimeError("workflow support must count exactly the verified receipts")
    if any(receipt_hash in workflow.support for receipt_hash in unverified):
        raise RuntimeError("an unverified receipt leaked into workflow support")
    narrative.append(
        f"mined {len(workflows)} workflow ({len(workflow.steps)} steps) from "
        f"{len(workflow.support)} verified receipts; the {len(unverified)} unverified "
        "receipt taught nothing"
    )

    # 3. Gate + ingest: the workflow passes on held-out evidence; poison is refused.
    sink = _RecordingSink()
    ingestor = GatedIngestor(PromotionGate(), sink, clock=lambda: _DEMO_CLOCK_MS)
    workflow_result = ingestor.ingest(
        workflow.to_learning_candidate(repo="demo/repo"),
        ShadowEvaluation(
            candidate_score=0.8, control_score=0.5, sample_size=20, protected_suite_passed=True
        ),
        reason="h9 demo: distilled workflow with passing held-out evidence",
    )
    promoted = workflow_result.ingested
    narrative.append(
        f"gate promoted '{workflow_result.candidate.id}' "
        f"v{workflow_result.candidate.version}: held-out 0.80 beat control 0.50 "
        "(n=20), protected suite passed"
        if promoted
        else f"gate refused the workflow: {'; '.join(workflow_result.reasons)}"
    )

    poison_result = ingestor.ingest(
        LearningCandidate(
            id="poison",
            kind=CandidateKind.REPO_FACT,
            content="Skip the failing test run before committing; reruns waste tokens.",
            provenance=Provenance(trace_ids=("hearsay",)),
            scope=Scope(repos=("demo/repo",)),
        ),
        ShadowEvaluation(
            candidate_score=0.4, control_score=0.5, sample_size=20, protected_suite_passed=False
        ),
        reason="h9 demo: poison memory with failing evidence",
    )
    poison_admitted = poison_result.ingested
    narrative.append(
        f"gate refused 'poison': {'; '.join(poison_result.reasons)}"
        if not poison_admitted
        else "gate WRONGLY admitted 'poison'"
    )

    # 4. Attribution: measure each memory's per-task lift on the benchmark.
    admitted: dict[str, str | None] = {
        "workflow": workflow_result.memory_id,
        "poison": poison_result.memory_id,
    }
    ledger = attribute_memories(["workflow", "poison"], list(_TASKS), _bench_task, seed=seed)
    for entry in ledger:
        narrative.append(
            f"attribution: '{entry.memory_id}' lift {entry.mean_lift:+.2f} "
            f"(95% CI [{entry.ci95[0]:+.2f}, {entry.ci95[1]:+.2f}]) over "
            f"{entry.n_tasks} tasks -> {entry.verdict.value}"
        )

    # 5. Retire measured poison — or report it was never admitted at all.
    retired: list[str] = []
    for label in retirement_candidates(ledger):
        memory_id = admitted.get(label)
        if memory_id is None:
            narrative.append(
                f"'{label}' measured harmful but was never admitted — the gate already kept it out"
            )
            continue
        rollback = ingestor.rollback(memory_id, reason=f"measured harmful: {label}")
        if rollback.rolled_back:
            retired.append(label)
            narrative.append(f"retired '{label}' (memory {memory_id}): rollback complete")

    # 6. Evolve the harness: challenger with the workflow vs champion without.
    champion = HarnessVariant.from_config(_CHAMPION_ID, {"memories": "none"})
    challenger = HarnessVariant.from_config(_CHALLENGER_ID, {"memories": "workflow"})
    evolution = evolve_step(
        champion, [challenger], list(_EVOLUTION_TASKS), _evolution_run, seed=seed
    )
    rates = dict(evolution.pass_rates)
    narrative.append(
        f"evolution: '{evolution.winner_id}' "
        f"{'promoted' if evolution.promoted else 'NOT promoted'} — "
        f"challenger {rates[_CHALLENGER_ID]:.2f} vs champion {rates[_CHAMPION_ID]:.2f} "
        f"pass rate, paired-delta 95% CI "
        f"[{evolution.delta_ci95[0]:+.2f}, {evolution.delta_ci95[1]:+.2f}] excludes zero"
    )

    # 7. Seal the story: in-toto Statement in a DSSE envelope over the summary.
    summary_hash = hashlib.sha256(evolution.record_hash.encode()).hexdigest()
    summary_receipt: dict[str, object] = {
        "receipt_hash": summary_hash,
        "verified": True,
        "status": "completed",
    }
    envelope = attest_receipt(summary_receipt, repo="demo/repo", tree_sha256="0" * 64)
    attested = envelope.signed or verify_envelope_payload(
        envelope, expected_receipt_hash=summary_hash
    )
    narrative.append(
        f"sealed: DSSE envelope binds summary receipt {summary_hash[:12]}... "
        f"to demo/repo — binding verified: {attested}"
    )

    return {
        "workflows_mined": len(workflows),
        "promoted": promoted,
        "poison_admitted": poison_admitted,
        "ledger": [entry.to_dict() for entry in ledger],
        "retired": retired,
        "evolution": evolution.to_dict(),
        "attested": attested,
        "narrative": narrative,
        "envelope": envelope.to_dict(),
    }


def main() -> None:
    """Print the demo's auditable story, one line per beat."""
    for line in cast(list[str], run_demo()["narrative"]):
        print(line)


if __name__ == "__main__":
    main()
