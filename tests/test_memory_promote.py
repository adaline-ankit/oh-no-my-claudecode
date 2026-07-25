"""Tests for the human approval path out of memory quarantine.

Autonomous writers stamp ``UNPROMOTED_SOURCE_PREFIX`` onto ``source_ref`` so the
entry is recorded but never auto-injected.  ``onmc memory promote`` is the only
way back out, and ``--revoke`` is the way back in.  These tests pin the
round-trip, the refusals, and the end-to-end effect on prompt injection.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.hooks.prompt_recall import (
    UNPROMOTED_SOURCE_PREFIX,
    compile_prompt_recall,
    is_unpromoted_source,
    unpromoted_source_ref,
)
from oh_no_my_claudecode.models import MemoryKind

_runner = CliRunner()


@pytest.fixture
def service(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> OnmcService:
    monkeypatch.chdir(sample_repo)
    svc = OnmcService(sample_repo)
    svc.init_project()
    return svc


def _add_quarantined(svc: OnmcService, *, title: str = "Autopilot win") -> str:
    memory = svc.add_memory(
        kind=MemoryKind.DECISION,
        title=title,
        summary="Cache invalidation should always go through the boundary.",
        source_type="session",
        source_ref=unpromoted_source_ref("autopilot:engine"),
        confidence=0.85,
    )
    assert is_unpromoted_source(memory.source_ref)
    return memory.id


# ── Service: promote ───────────────────────────────────────────────────────────


def test_promote_strips_the_unpromoted_prefix(service: OnmcService) -> None:
    memory_id = _add_quarantined(service)

    updated = service.promote_memory(memory_id)

    assert updated.source_ref == "autopilot:engine"
    assert not is_unpromoted_source(updated.source_ref)


def test_promote_persists_through_storage(service: OnmcService) -> None:
    memory_id = _add_quarantined(service)

    service.promote_memory(memory_id)

    reloaded = service.get_memory(memory_id)
    assert reloaded is not None
    assert not is_unpromoted_source(reloaded.source_ref)


def test_promote_touches_updated_at(service: OnmcService) -> None:
    memory_id = _add_quarantined(service)
    before = service.get_memory(memory_id)
    assert before is not None

    updated = service.promote_memory(memory_id)

    assert updated.updated_at >= before.updated_at


def test_promote_leaves_content_and_trust_signals_untouched(
    service: OnmcService,
) -> None:
    memory_id = _add_quarantined(service)
    before = service.get_memory(memory_id)
    assert before is not None

    updated = service.promote_memory(memory_id)

    assert updated.title == before.title
    assert updated.summary == before.summary
    assert updated.confidence == before.confidence
    assert updated.feedback_score == before.feedback_score


def test_promote_unknown_id_raises_lookup_error(service: OnmcService) -> None:
    with pytest.raises(LookupError, match="Memory not found"):
        service.promote_memory("does-not-exist")


def test_promote_already_promoted_raises_value_error(service: OnmcService) -> None:
    memory = service.add_memory(
        kind=MemoryKind.INVARIANT,
        title="Human-written invariant",
        summary="Do not bypass the cache boundary.",
    )

    with pytest.raises(ValueError, match="already promoted"):
        service.promote_memory(memory.id)


def test_promote_is_not_repeatable(service: OnmcService) -> None:
    """A second promote is a refusal, not a silent no-op."""
    memory_id = _add_quarantined(service)
    service.promote_memory(memory_id)

    with pytest.raises(ValueError, match="already promoted"):
        service.promote_memory(memory_id)


# ── Service: the ONMC_LEARNING kill switch ─────────────────────────────────────


def test_promote_refuses_when_learning_is_disabled(
    service: OnmcService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory_id = _add_quarantined(service)
    monkeypatch.setenv("ONMC_LEARNING", "0")

    with pytest.raises(ValueError, match="ONMC_LEARNING"):
        service.promote_memory(memory_id)

    still = service.get_memory(memory_id)
    assert still is not None
    assert is_unpromoted_source(still.source_ref)


def test_promote_fails_closed_when_the_kill_switch_cannot_be_read(
    service: OnmcService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unresolvable kill switch must refuse promotion, not assume 'on'."""
    memory_id = _add_quarantined(service)

    def _boom() -> bool:
        raise RuntimeError("kill switch unavailable")

    monkeypatch.setattr(
        "oh_no_my_claudecode.learning.activation.is_learning_enabled",
        _boom,
    )

    with pytest.raises(ValueError, match="ONMC_LEARNING"):
        service.promote_memory(memory_id)


def test_revoke_is_allowed_while_learning_is_disabled(
    service: OnmcService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The safe direction must never be blocked by the kill switch."""
    memory = service.add_memory(
        kind=MemoryKind.DECISION,
        title="Promoted decision",
        summary="Route writes through the repository layer.",
    )
    monkeypatch.setenv("ONMC_LEARNING", "0")

    updated = service.promote_memory(memory.id, revoke=True)

    assert is_unpromoted_source(updated.source_ref)


# ── Service: revoke ────────────────────────────────────────────────────────────


def test_revoke_restamps_the_prefix(service: OnmcService) -> None:
    memory = service.add_memory(
        kind=MemoryKind.DECISION,
        title="Promoted decision",
        summary="Route writes through the repository layer.",
    )

    updated = service.promote_memory(memory.id, revoke=True)

    assert updated.source_ref.startswith(UNPROMOTED_SOURCE_PREFIX)
    assert is_unpromoted_source(updated.source_ref)


def test_revoke_already_unpromoted_raises_value_error(service: OnmcService) -> None:
    memory_id = _add_quarantined(service)

    with pytest.raises(ValueError, match="already unpromoted"):
        service.promote_memory(memory_id, revoke=True)


def test_promote_then_revoke_round_trips(service: OnmcService) -> None:
    memory_id = _add_quarantined(service)

    promoted = service.promote_memory(memory_id)
    revoked = service.promote_memory(memory_id, revoke=True)

    assert revoked.source_ref == unpromoted_source_ref(promoted.source_ref)
    assert is_unpromoted_source(revoked.source_ref)


# ── End-to-end: quarantine actually lifts ──────────────────────────────────────


def test_promoted_memory_becomes_injectable(service: OnmcService) -> None:
    """The point of the command: injection before vs after, nothing else changed."""
    memory_id = _add_quarantined(service, title="Cache invalidation boundary")
    _, _, storage = service._load_context()  # noqa: SLF001

    before, _ = compile_prompt_recall(storage, "cache invalidation", limit=5)
    assert "Cache invalidation boundary" not in before

    service.promote_memory(memory_id)

    after, _ = compile_prompt_recall(storage, "cache invalidation", limit=5)
    assert "Cache invalidation boundary" in after


def test_revoked_memory_stops_being_injectable(service: OnmcService) -> None:
    memory_id = _add_quarantined(service, title="Cache invalidation boundary")
    service.promote_memory(memory_id)
    _, _, storage = service._load_context()  # noqa: SLF001

    service.promote_memory(memory_id, revoke=True)

    after, _ = compile_prompt_recall(storage, "cache invalidation", limit=5)
    assert "Cache invalidation boundary" not in after


# ── CLI ────────────────────────────────────────────────────────────────────────


def test_cli_promote_reports_the_cleaned_source_ref(service: OnmcService) -> None:
    memory_id = _add_quarantined(service)

    result = _runner.invoke(app, ["memory", "promote", memory_id], color=False)

    assert result.exit_code == 0
    assert UNPROMOTED_SOURCE_PREFIX not in result.stdout
    reloaded = service.get_memory(memory_id)
    assert reloaded is not None
    assert not is_unpromoted_source(reloaded.source_ref)


def test_cli_promote_revoke_requarantines(service: OnmcService) -> None:
    memory = service.add_memory(
        kind=MemoryKind.DECISION,
        title="Promoted decision",
        summary="Route writes through the repository layer.",
    )

    result = _runner.invoke(
        app, ["memory", "promote", memory.id, "--revoke"], color=False
    )

    assert result.exit_code == 0
    reloaded = service.get_memory(memory.id)
    assert reloaded is not None
    assert is_unpromoted_source(reloaded.source_ref)


def test_cli_promote_unknown_id_exits_nonzero(service: OnmcService) -> None:
    result = _runner.invoke(app, ["memory", "promote", "no-such-id"], color=False)

    assert result.exit_code == 1
    assert "Memory not found" in result.stdout


def test_cli_promote_already_promoted_exits_nonzero(service: OnmcService) -> None:
    memory = service.add_memory(
        kind=MemoryKind.INVARIANT,
        title="Human-written invariant",
        summary="Do not bypass the cache boundary.",
    )

    result = _runner.invoke(app, ["memory", "promote", memory.id], color=False)

    assert result.exit_code == 1
    assert "already promoted" in result.stdout


def test_cli_has_no_bulk_promote_flag() -> None:
    """Per-id only: a bulk approval would defeat the gate."""
    result = _runner.invoke(app, ["memory", "promote", "--help"], color=False)

    assert result.exit_code == 0
    assert "--all" not in result.stdout
    assert "--auto" not in result.stdout
