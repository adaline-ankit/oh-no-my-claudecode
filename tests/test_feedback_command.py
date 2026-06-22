from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import MemoryKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_memory(sample_repo: Path) -> str:
    """Initialise an onmc project and seed one memory; return its id."""
    service = OnmcService(sample_repo)
    service.init_project()
    memory = service.add_memory(
        kind=MemoryKind.INVARIANT,
        title="Cache boundary must not be bypassed",
        summary="All writes must go through the shared cache boundary.",
        confidence=0.75,
    )
    return memory.id


# ---------------------------------------------------------------------------
# Service-level unit tests
# ---------------------------------------------------------------------------


def test_feedback_up_increases_feedback_score_and_confidence(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    memory = service.add_memory(
        kind=MemoryKind.INVARIANT,
        title="Boundary test",
        summary="Do not bypass the boundary.",
        confidence=0.75,
    )
    initial_score = memory.feedback_score
    initial_conf = memory.confidence

    updated = service.feedback(memory.id, "up")

    assert updated.feedback_score > initial_score
    assert updated.confidence > initial_conf
    assert updated.feedback_score == pytest.approx(
        initial_score + OnmcService._FEEDBACK_UP_SCORE, abs=1e-6
    )
    assert updated.confidence == pytest.approx(
        initial_conf + OnmcService._FEEDBACK_UP_CONFIDENCE, abs=1e-6
    )


def test_feedback_down_decreases_feedback_score_and_confidence(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    memory = service.add_memory(
        kind=MemoryKind.GOTCHA,
        title="Misleading note",
        summary="This memory is wrong.",
        confidence=0.75,
    )
    initial_score = memory.feedback_score
    initial_conf = memory.confidence

    updated = service.feedback(memory.id, "down")

    assert updated.feedback_score < initial_score
    assert updated.confidence < initial_conf
    assert updated.feedback_score == pytest.approx(
        initial_score - OnmcService._FEEDBACK_DOWN_SCORE, abs=1e-6
    )
    assert updated.confidence == pytest.approx(
        initial_conf - OnmcService._FEEDBACK_DOWN_CONFIDENCE, abs=1e-6
    )


def test_feedback_down_clamps_confidence_at_floor(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    # Start from a very low confidence so repeated downs hit the floor.
    memory = service.add_memory(
        kind=MemoryKind.GOTCHA,
        title="Low confidence memory",
        summary="Starting near zero confidence.",
        confidence=OnmcService._FEEDBACK_CONFIDENCE_FLOOR + 0.01,
    )

    updated = service.feedback(memory.id, "down")

    assert updated.confidence >= OnmcService._FEEDBACK_CONFIDENCE_FLOOR


def test_feedback_up_clamps_feedback_score_at_one(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    memory = service.add_memory(
        kind=MemoryKind.INVARIANT,
        title="Already trusted",
        summary="Very trusted memory.",
        confidence=0.9,
    )
    # Drive feedback_score close to the ceiling.
    for _ in range(5):
        memory = service.feedback(memory.id, "up")

    assert memory.feedback_score <= 1.0
    assert memory.confidence <= 1.0


def test_feedback_down_clamps_feedback_score_at_minus_one(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    memory = service.add_memory(
        kind=MemoryKind.FAILED_APPROACH,
        title="Repeatedly wrong",
        summary="This keeps being wrong.",
        confidence=0.8,
    )
    for _ in range(5):
        memory = service.feedback(memory.id, "down")

    assert memory.feedback_score >= -1.0


def test_feedback_touches_updated_at(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    memory = service.add_memory(
        kind=MemoryKind.DECISION,
        title="Decision memory",
        summary="Was made intentionally.",
        confidence=0.8,
    )
    original_updated_at = memory.updated_at

    updated = service.feedback(memory.id, "up")

    assert updated.updated_at >= original_updated_at


def test_feedback_note_appended_to_details(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    memory = service.add_memory(
        kind=MemoryKind.GOTCHA,
        title="Note test",
        summary="Original summary.",
        confidence=0.7,
    )

    updated = service.feedback(memory.id, "down", note="outdated after refactor")

    assert "outdated after refactor" in updated.details


def test_feedback_note_none_does_not_corrupt_details(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    original_details = "Original details text."
    memory = service.add_memory(
        kind=MemoryKind.INVARIANT,
        title="No note test",
        summary=original_details,
        confidence=0.7,
    )

    updated = service.feedback(memory.id, "up")

    # details must remain unchanged when no note is given
    assert updated.details == original_details


def test_feedback_unknown_id_raises_lookup_error(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    with pytest.raises(LookupError, match="Memory not found"):
        service.feedback("non-existent-id-xyz", "up")


def test_feedback_bad_direction_raises_value_error(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    memory = service.add_memory(
        kind=MemoryKind.INVARIANT,
        title="Direction test",
        summary="Test memory.",
        confidence=0.7,
    )

    with pytest.raises(ValueError, match="up.*down"):
        service.feedback(memory.id, "sideways")


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_cli_feedback_up_exits_zero_and_shows_score(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    memory_id = _seed_memory(sample_repo)

    result = runner.invoke(app, ["feedback", memory_id, "up"])

    assert result.exit_code == 0
    assert "up" in result.stdout.lower() or "feedback_score" in result.stdout.lower()


def test_cli_feedback_down_exits_zero(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    memory_id = _seed_memory(sample_repo)

    result = runner.invoke(app, ["feedback", memory_id, "down"])

    assert result.exit_code == 0


def test_cli_feedback_unknown_id_exits_nonzero(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    _seed_memory(sample_repo)

    result = runner.invoke(app, ["feedback", "does-not-exist-xyz", "up"])

    assert result.exit_code != 0


def test_cli_feedback_bad_direction_exits_nonzero(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    memory_id = _seed_memory(sample_repo)

    result = runner.invoke(app, ["feedback", memory_id, "sideways"])

    assert result.exit_code != 0


def test_cli_feedback_json_output_shape(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    memory_id = _seed_memory(sample_repo)

    result = runner.invoke(app, ["feedback", memory_id, "up", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["id"] == memory_id
    assert data["direction"] == "up"
    assert "feedback_score" in data
    assert "confidence" in data
    assert "updated_at" in data


def test_cli_feedback_json_down_shape(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    memory_id = _seed_memory(sample_repo)

    result = runner.invoke(app, ["feedback", memory_id, "down", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["direction"] == "down"
    assert data["feedback_score"] < 0  # started at 0, went down


def test_cli_feedback_with_note(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    memory_id = _seed_memory(sample_repo)

    result = runner.invoke(
        app,
        ["feedback", memory_id, "down", "--note", "stale after refactor", "--json"],
    )

    assert result.exit_code == 0
    # Verify the memory details were updated by re-reading through service.
    service = OnmcService(sample_repo)
    updated = service.get_memory(memory_id)
    assert updated is not None
    assert "stale after refactor" in updated.details
