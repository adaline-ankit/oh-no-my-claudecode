"""E4 compaction-policy scoring: safety gate, ranking, baseline, determinism."""

from __future__ import annotations

from oh_no_my_claudecode.context_engine.compaction_gate import Constraint
from oh_no_my_claudecode.experiment.compaction_score import (
    FULL_CONTEXT_POLICY,
    CompactionPolicy,
    PolicyScore,
    score_policies,
)

CONSTRAINTS = (
    Constraint("no-force-push", "never force-push to main"),
    Constraint("no-secrets", "do not log secrets"),
)

_FILLER = "\n".join(f"chatter line {i}: much ado about nothing at all here" for i in range(20))

CONTEXTS = (
    f"RULE: never force-push to main\nRULE: do not log secrets\n{_FILLER}",
    f"{_FILLER}\nRULE: do not log secrets\nRULE: never force-push to main",
)

TASK_IDS = ("t1", "t2", "t3", "t4")

# task_runner has no entry for "decaying" — if the scorer ever ran a rejected
# policy's tasks, the KeyError would fail every test below (fail-closed proof).
_PASSES = {
    FULL_CONTEXT_POLICY: {"t1", "t2"},
    "faithful": {"t1", "t2", "t3", "t4"},
}


def _faithful(text: str) -> str:
    """Keeps every constraint-bearing line, drops the filler."""
    return "\n".join(ln for ln in text.splitlines() if any(c.holds_in(ln) for c in CONSTRAINTS))


def _decaying(text: str) -> str:
    """Drops the constraint lines — the governance-decay failure mode."""
    return "\n".join(ln for ln in text.splitlines() if not any(c.holds_in(ln) for c in CONSTRAINTS))


def _score(seed: int = 7) -> list[PolicyScore]:
    return score_policies(
        [CompactionPolicy("faithful", _faithful), CompactionPolicy("decaying", _decaying)],
        CONTEXTS,
        CONSTRAINTS,
        lambda policy_name, task_id: task_id in _PASSES[policy_name],
        TASK_IDS,
        seed=seed,
    )


def test_faithful_policy_ranked_first_with_positive_lift() -> None:
    top = _score()[0]
    assert top.name == "faithful"
    assert not top.rejected
    assert top.violations == 0
    assert top.pass_rate == 1.0
    assert top.delta_vs_full == 0.5
    assert top.mean_tokens_freed > 0
    assert top.lift_per_kilotoken > 0
    lo, hi = top.delta_ci95
    assert lo <= top.delta_vs_full <= hi
    assert top.to_dict()["lift_per_kilotoken"] == top.lift_per_kilotoken


def test_decaying_policy_rejected_and_never_ranked_above_safe() -> None:
    scores = _score()
    decaying = next(s for s in scores if s.name == "decaying")
    assert decaying.rejected
    assert decaying.violations == 4  # 2 constraints lost on each of 2 contexts
    assert decaying.pass_rate == 0.0
    assert decaying.lift_per_kilotoken == 0.0
    assert scores[-1] is decaying
    assert all(not s.rejected for s in scores[:-1])


def test_identity_baseline_has_zero_delta() -> None:
    base = next(s for s in _score() if s.name == FULL_CONTEXT_POLICY)
    assert not base.rejected
    assert base.delta_vs_full == 0.0
    assert base.delta_ci95 == (0.0, 0.0)
    assert base.mean_tokens_freed == 0.0
    assert base.lift_per_kilotoken == 0.0
    assert base.pass_rate == 0.5


def test_deterministic_across_calls() -> None:
    assert _score() == _score()
