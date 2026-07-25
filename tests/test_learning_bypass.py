"""Tests for activation enforcement — the kill switch and the promote-before-activate guard.

Where ``test_learning_gate.py`` proves nothing is *promoted* without held-out
evidence, this module proves the other half: nothing is *activated* without
proving that promotion happened, and one flag makes all learned behaviour inert.

Coverage
--------
1.  ``ONMC_LEARNING=0`` is a single kill switch: it disables activation of a
    genuinely-promoted candidate, suppresses promotion via ``env_gate``, and
    short-circuits the live ``GatedIngestor`` write seam before the sink.
2.  ``require_promoted`` refuses every non-PROMOTED/MONITORED state, a
    PROMOTED-looking candidate with no promotion record, a stale one, an
    out-of-scope one, and one whose record lacks provenance.
3.  A promoted candidate carries provenance + scope + version + a rollback path,
    and ``require_promoted`` returns the record that proves it.
4.  Hostile content is refused at activation too, reusing the adversarial payload
    from ``test_m4_security_challenges`` — the existing sanitize path does the
    detecting; nothing is duplicated here.
"""

from __future__ import annotations

import pytest

from oh_no_my_claudecode.experiment.contracts import (
    ArtifactRef,
    CandidateState,
    MetricLabel,
)
from oh_no_my_claudecode.learning import (
    LEARNING_ENABLED_ENV,
    ActivationRefusedError,
    ActivationTarget,
    AdvanceEvent,
    CandidateKind,
    LearningCandidate,
    Provenance,
    RefreshPolicy,
    Scope,
    ShadowEvaluation,
    active_candidates,
    advance,
    can_roll_back,
    check_activation,
    env_gate,
    is_learning_enabled,
    require_promoted,
    rollback,
    scan,
)
from oh_no_my_claudecode.learning.ingest import GatedIngestor, IngestedMemory
from test_m4_security_challenges import MALICIOUS_BLOB

# ---------------------------------------------------------------------------
# Fixtures / helpers — same shapes as test_learning_gate / test_learning_ingest
# ---------------------------------------------------------------------------

_GOOD_CONTENT = (
    "When editing files under packages/fabric, run the workspace type-check "
    "before committing; the pre-commit hook enforces it."
)

_ON: dict[str, str] = {}
_OFF: dict[str, str] = {LEARNING_ENABLED_ENV: "0"}

_NOW = 6_000


def _artifact() -> ArtifactRef:
    return ArtifactRef.of(b"trace-evidence-blob", "application/json")


def _scope() -> Scope:
    return Scope(repos=("acme/pegasus",), paths=("packages/fabric/**",), languages=("python",))


def _target() -> ActivationTarget:
    return ActivationTarget(
        repo="acme/pegasus",
        path="packages/fabric/src/x.py",
        language="python",
    )


def _winning_eval() -> ShadowEvaluation:
    return ShadowEvaluation(
        candidate_score=0.82,
        control_score=0.61,
        sample_size=40,
        protected_suite_passed=True,
        metric_label=MetricLabel.MEASURED,
    )


def _candidate(
    *,
    content: str = _GOOD_CONTENT,
    cid: str = "cand-fabric-typecheck",
    provenance: Provenance | None = None,
) -> LearningCandidate:
    return LearningCandidate(
        id=cid,
        kind=CandidateKind.REPO_FACT,
        content=content,
        provenance=Provenance(trace_ids=("trace-abc",), artifacts=(_artifact(),))
        if provenance is None
        else provenance,
        created_at_ms=1_000,
    )


def _walk_to_shadow(cand: LearningCandidate) -> LearningCandidate:
    cand = advance(cand, AdvanceEvent(to=CandidateState.CANDIDATE))
    cand = advance(cand, AdvanceEvent(to=CandidateState.SANITIZED))
    cand = advance(cand, AdvanceEvent(to=CandidateState.SCOPED, scope=_scope()))
    return advance(
        cand,
        AdvanceEvent(to=CandidateState.SHADOW_EVALUATED, evaluation=_winning_eval()),
    )


def _promoted(cand: LearningCandidate | None = None) -> LearningCandidate:
    return advance(
        _walk_to_shadow(cand if cand is not None else _candidate()),
        AdvanceEvent(to=CandidateState.PROMOTED, at_ms=5_000, reason="beats control"),
    )


class RecordingSink:
    """Minimal ``MemorySink`` double — proves whether the store was touched."""

    def __init__(self) -> None:
        self.writes: list[IngestedMemory] = []
        self.removes: list[str] = []

    def write(self, memory: IngestedMemory) -> str:
        self.writes.append(memory)
        return memory.memory_id

    def remove(self, memory_id: str) -> bool:
        self.removes.append(memory_id)
        return True


# ---------------------------------------------------------------------------
# 1. The kill switch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", " Off "])
def test_kill_switch_recognises_disabling_values(value: str) -> None:
    assert is_learning_enabled({LEARNING_ENABLED_ENV: value}) is False


@pytest.mark.parametrize("env", [{}, {LEARNING_ENABLED_ENV: "1"}, {LEARNING_ENABLED_ENV: "yes"}])
def test_learning_is_enabled_by_default(env: dict[str, str]) -> None:
    assert is_learning_enabled(env) is True


def test_kill_switch_disables_activation_of_a_promoted_candidate() -> None:
    """The same genuinely-promoted candidate is active ON and inert OFF."""
    promoted = _promoted()

    assert check_activation(promoted, now_ms=_NOW, target=_target(), env=_ON).active is True

    decision = check_activation(promoted, now_ms=_NOW, target=_target(), env=_OFF)
    assert decision.active is False
    assert decision.learning_enabled is False
    assert decision.promotion is None
    assert any("kill-switch" in r for r in decision.reasons)

    with pytest.raises(ActivationRefusedError) as exc:
        require_promoted(promoted, now_ms=_NOW, target=_target(), env=_OFF)
    assert any("kill-switch" in r for r in exc.value.reasons)


def test_kill_switch_suppresses_promotion_via_env_gate() -> None:
    """One flag closes the promotion door as well as the activation door."""
    shadow = _walk_to_shadow(_candidate())

    assert env_gate(env=_ON).would_promote(shadow) is True
    assert env_gate(env=_OFF).would_promote(shadow) is False
    assert any(
        "learning-disabled" in r for r in env_gate(env=_OFF).evaluate(shadow).reasons
    )


def test_kill_switch_blocks_the_gated_ingest_write_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the switch off the live seam never reaches the store."""
    monkeypatch.setenv(LEARNING_ENABLED_ENV, "0")
    sink = RecordingSink()
    ingestor = GatedIngestor(env_gate(), sink, clock=lambda: 5_000)

    result = ingestor.ingest(_candidate().evolve(scope=_scope()), _winning_eval())

    assert result.rejected
    assert result.memory_id is None
    assert any("kill-switch" in r for r in result.reasons)
    assert sink.writes == []
    assert ingestor.ingested_ids() == ()


def test_gated_ingest_still_writes_with_the_switch_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control arm for the test above — the switch is the only difference."""
    monkeypatch.delenv(LEARNING_ENABLED_ENV, raising=False)
    sink = RecordingSink()
    ingestor = GatedIngestor(env_gate(), sink, clock=lambda: 5_000)

    result = ingestor.ingest(_candidate().evolve(scope=_scope()), _winning_eval())

    assert result.ingested is True
    assert len(sink.writes) == 1


# ---------------------------------------------------------------------------
# 2. The guard refuses anything not proven PROMOTED
# ---------------------------------------------------------------------------


def test_guard_refuses_every_pre_promotion_state() -> None:
    """No state before PROMOTED can produce an activation authorization."""
    cand = _candidate()
    stages = [cand]
    cand = advance(cand, AdvanceEvent(to=CandidateState.CANDIDATE))
    stages.append(cand)
    cand = advance(cand, AdvanceEvent(to=CandidateState.SANITIZED))
    stages.append(cand)
    cand = advance(cand, AdvanceEvent(to=CandidateState.SCOPED, scope=_scope()))
    stages.append(cand)
    cand = advance(
        cand, AdvanceEvent(to=CandidateState.SHADOW_EVALUATED, evaluation=_winning_eval())
    )
    stages.append(cand)

    for stage in stages:
        decision = check_activation(stage, now_ms=_NOW, env=_ON)
        assert decision.active is False, f"{stage.state.value} must not activate"
        assert any("not-promoted" in r for r in decision.reasons)
        assert any("no-promotion-record" in r for r in decision.reasons)
        with pytest.raises(ActivationRefusedError):
            require_promoted(stage, now_ms=_NOW, env=_ON)


def test_guard_refuses_a_forged_promoted_state_without_a_record() -> None:
    """A candidate that merely *claims* PROMOTED is refused — the record is the proof."""
    forged = _candidate(cid="cand-forged").evolve(
        state=CandidateState.PROMOTED,
        scope=_scope(),
        version=1,
    )
    assert forged.promotion is None

    decision = check_activation(forged, now_ms=_NOW, env=_ON)
    assert decision.active is False
    assert any("no-promotion-record" in r for r in decision.reasons)
    with pytest.raises(ActivationRefusedError):
        require_promoted(forged, now_ms=_NOW, env=_ON)


def test_guard_refuses_rolled_back_and_superseded_candidates() -> None:
    """Reversed / retired artifacts keep their record but lose activation."""
    promoted = _promoted()

    rolled = rollback(promoted, at_ms=7_000, reason="incident")
    monitored = advance(promoted, AdvanceEvent(to=CandidateState.MONITORED, at_ms=7_000))
    superseded = advance(monitored, AdvanceEvent(to=CandidateState.SUPERSEDED, at_ms=8_000))

    # MONITORED is still a live state; the two terminal ones are not.
    assert check_activation(monitored, now_ms=9_000, target=_target(), env=_ON).active is True

    for dead in (rolled, superseded):
        decision = check_activation(dead, now_ms=9_000, target=_target(), env=_ON)
        assert decision.active is False
        assert dead.promotion is not None  # the record survives...
        assert any("not-promoted" in r for r in decision.reasons)  # ...but authorizes nothing
        assert any("no-rollback-path" in r for r in decision.reasons)
        assert can_roll_back(dead) is False


def test_guard_refuses_stale_promoted_candidate() -> None:
    """Expired learning is inert even while its state still reads PROMOTED."""
    promoted = _promoted(_candidate().evolve(refresh=RefreshPolicy(expires_at_ms=10_000)))

    assert check_activation(promoted, now_ms=9_999, target=_target(), env=_ON).active is True

    decision = check_activation(promoted, now_ms=10_000, target=_target(), env=_ON)
    assert decision.active is False
    assert any("stale" in r for r in decision.reasons)
    with pytest.raises(ActivationRefusedError):
        require_promoted(promoted, now_ms=10_001, target=_target(), env=_ON)


def test_guard_refuses_out_of_scope_target() -> None:
    """Learning stays bounded to the scope it was promoted for."""
    promoted = _promoted()
    foreign = ActivationTarget(repo="acme/other", path="services/api/main.py", language="go")

    decision = check_activation(promoted, now_ms=_NOW, target=foreign, env=_ON)
    assert decision.active is False
    assert any("out-of-scope" in r for r in decision.reasons)
    with pytest.raises(ActivationRefusedError):
        require_promoted(promoted, now_ms=_NOW, target=foreign, env=_ON)


def test_guard_refuses_promotion_without_provenance() -> None:
    """A promotion record with no trace ids or artifacts is not honest provenance."""
    anonymous = _promoted(_candidate(cid="cand-anon", provenance=Provenance()))

    assert anonymous.promotion is not None
    assert anonymous.promotion.provenance.is_empty is True

    decision = check_activation(anonymous, now_ms=_NOW, target=_target(), env=_ON)
    assert decision.active is False
    assert any("no-provenance" in r for r in decision.reasons)


def test_activation_decision_reports_every_violated_clause() -> None:
    """The audit is exhaustive, not first-failure — an auditor sees all of it."""
    rolled = rollback(
        _promoted(_candidate().evolve(refresh=RefreshPolicy(expires_at_ms=1_000))),
        at_ms=7_000,
    )
    decision = check_activation(
        rolled,
        now_ms=9_000,
        target=ActivationTarget(repo="acme/other"),
        env=_OFF,
    )

    codes = {r.split(":", 1)[0] for r in decision.reasons}
    assert {"kill-switch", "not-promoted", "out-of-scope", "stale", "no-rollback-path"} <= codes
    assert decision.refused is True
    assert decision.to_dict()["active"] is False


# ---------------------------------------------------------------------------
# 3. A promoted candidate carries provenance + scope + version + rollback
# ---------------------------------------------------------------------------


def test_promoted_candidate_carries_provenance_scope_version_and_rollback_path() -> None:
    promoted = _promoted()

    record = require_promoted(promoted, now_ms=_NOW, target=_target(), env=_ON)

    # Provenance — honest and non-empty.
    assert record.provenance.trace_ids == ("trace-abc",)
    assert record.provenance.artifacts == (_artifact(),)
    assert record.provenance.is_empty is False

    # Scope — bounded, and it covers the target we proved against.
    assert record.scope == _scope()
    assert record.scope.is_empty is False
    assert record.scope.matches(repo="acme/pegasus", path="packages/fabric/a.py", language="python")

    # Version — bumped on promotion.
    assert record.version == 1
    assert promoted.version == 1

    # Held-out evidence travels with the authorization.
    assert record.evaluation.held_out is True
    assert record.evaluation.delta == pytest.approx(0.21)

    # Rollback path — reachable, and taking it makes the artifact inert.
    assert can_roll_back(promoted) is True
    reversed_candidate = rollback(promoted, at_ms=9_000, reason="regression")
    assert reversed_candidate.state is CandidateState.ROLLED_BACK
    assert check_activation(reversed_candidate, now_ms=9_500, env=_ON).active is False


def test_active_candidates_filters_a_batch_and_empties_under_kill_switch() -> None:
    """The batch form for context assembly: only proven artifacts come back."""
    good = _promoted()
    unproven = _walk_to_shadow(_candidate(cid="cand-unproven"))
    dead = rollback(_promoted(_candidate(cid="cand-dead")), at_ms=7_000)
    batch = (good, unproven, dead)

    assert active_candidates(batch, now_ms=_NOW, target=_target(), env=_ON) == (good,)
    assert active_candidates(batch, now_ms=_NOW, target=_target(), env=_OFF) == ()


# ---------------------------------------------------------------------------
# 4. Hostile content is refused at activation too
# ---------------------------------------------------------------------------


def test_guard_refuses_hostile_candidate_using_existing_challenge_payload() -> None:
    """Reuses the adversarial blob from the M4 challenge suite.

    The sanitizer is already proven to detect it there; what is asserted here is
    that the *activation* guard also refuses a candidate carrying findings, so a
    poisoned artifact smuggled into a PROMOTED-looking state still never goes
    live.
    """
    findings = scan(MALICIOUS_BLOB)
    assert findings, "the existing sanitize path must flag the challenge payload"

    smuggled = _candidate(content=MALICIOUS_BLOB, cid="cand-poison").evolve(
        state=CandidateState.PROMOTED,
        findings=findings,
        scope=_scope(),
    )
    # Give it a real promotion record so ONLY the sanitize clause can refuse it.
    authorized = _promoted()
    smuggled = smuggled.evolve(promotion=authorized.promotion, version=1)

    decision = check_activation(smuggled, now_ms=_NOW, target=_target(), env=_ON)
    assert decision.active is False
    assert any("not-sanitized-clean" in r for r in decision.reasons)
    with pytest.raises(ActivationRefusedError):
        require_promoted(smuggled, now_ms=_NOW, target=_target(), env=_ON)
