"""Tests for the ``onmc memstage`` write-approval staging queue.

Covers the pure queue core (deterministic, dependency-injected) and the
auto-discovered CLI surface (exercised via flags + JSON / exit codes only —
never by asserting Rich ``--help`` text).

What is verified
----------------
- stage → appears in list_pending; does NOT appear in memory store
- diff renders a unified-diff with the proposed content as additions
- approve → proposal removed from queue; persists to the memory store
- reject → proposal dropped from queue; audit trail is kept
- deterministic ids (same content + seq → same id; different seq → different id)
- approve with an unknown id → graceful LookupError
- reject with an unknown id → graceful LookupError
- ``--json`` envelopes are valid JSON with expected keys
- empty queue is graceful (no crash, empty list)
- audit list reflects approve/reject history
- CLI: add, list, diff, approve, reject surface — reachable and correct
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from oh_no_my_claudecode.memstage.commands import register
from oh_no_my_claudecode.memstage.queue import (
    AuditRecord,
    StagedProposal,
    approve,
    diff,
    get,
    list_audit,
    list_pending,
    reject,
    stage,
)
from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind, SourceType

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory_entry(memory_id: str = "mem-test-001") -> MemoryEntry:
    """Minimal valid MemoryEntry for mocking approve."""
    from datetime import UTC, datetime

    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)
    return MemoryEntry(
        id=memory_id,
        kind=MemoryKind.DOC_FACT,
        title="Test Title",
        summary="Test summary",
        details="Test summary",
        source_type=SourceType.MANUAL,
        source_ref="memstage:ms-abc123",
        tags=[],
        confidence=0.75,
        created_at=now,
        updated_at=now,
    )


def _make_service_mock(memory_id: str = "mem-test-001") -> MagicMock:
    """A mock OnmcService whose add_manual_memory returns a valid MemoryEntry."""
    from oh_no_my_claudecode.core.service import OnmcService  # noqa: PLC0415

    mock = MagicMock(spec=OnmcService)
    mock.add_manual_memory.return_value = _make_memory_entry(memory_id)
    return mock


def _app() -> typer.Typer:
    """Fresh Typer app with memstage registered (sentinel keeps it a subgroup)."""
    app = typer.Typer()

    @app.command("__sentinel__")
    def _sentinel() -> None:  # pragma: no cover
        ...

    register(app)
    return app


# ---------------------------------------------------------------------------
# 1. stage → appears in list_pending; does NOT affect memory store
# ---------------------------------------------------------------------------


def test_stage_appears_in_list_pending(tmp_path: Path) -> None:
    proposal = stage(
        tmp_path,
        kind="doc_fact",
        title="Always run tests first",
        summary="Run the full test suite before pushing",
        reason="CI catches it anyway but earlier is better",
    )
    assert proposal.id.startswith("ms-")
    assert proposal.kind == "doc_fact"
    assert proposal.title == "Always run tests first"

    pending = list_pending(tmp_path)
    assert len(pending) == 1
    assert pending[0].id == proposal.id


def test_stage_does_not_write_to_storage(tmp_path: Path) -> None:
    """Staging a proposal must NOT touch the memory store."""
    stage(
        tmp_path,
        kind="gotcha",
        title="Stripe secret rotates",
        summary="Webhook secret rotates on every redeploy",
    )
    # The SQLite db should not exist (we never called add_manual_memory).
    db_path = tmp_path / ".onmc" / "memory.db"
    assert not db_path.exists()


def test_stage_persisted_under_onmc_memstage(tmp_path: Path) -> None:
    proposal = stage(tmp_path, kind="doc_fact", title="T", summary="S")
    expected = tmp_path / ".onmc" / "memstage" / "pending" / f"{proposal.id}.json"
    assert expected.is_file()


# ---------------------------------------------------------------------------
# 2. diff renders unified-diff with proposed content as additions
# ---------------------------------------------------------------------------


def test_diff_renders_additions(tmp_path: Path) -> None:
    proposal = stage(tmp_path, kind="decision", title="Use uv", summary="Use uv for deps")
    output = diff(tmp_path, proposal.id)
    assert "+kind:    decision" in output
    assert "+title:   Use uv" in output
    assert "+summary: Use uv for deps" in output
    assert "---" in output  # unified diff header present


def test_diff_unknown_id_returns_error_string(tmp_path: Path) -> None:
    output = diff(tmp_path, "ms-nonexistent-0000")
    assert output.startswith("error:")
    assert "ms-nonexistent-0000" in output


def test_diff_includes_reason_when_set(tmp_path: Path) -> None:
    proposal = stage(
        tmp_path,
        kind="gotcha",
        title="T",
        summary="S",
        reason="Saved 3 hours debugging",
    )
    output = diff(tmp_path, proposal.id)
    assert "+reason:  Saved 3 hours debugging" in output


# ---------------------------------------------------------------------------
# 3. approve → removes from queue; persists to store; audit trail
# ---------------------------------------------------------------------------


def test_approve_removes_from_queue(tmp_path: Path) -> None:
    proposal = stage(tmp_path, kind="doc_fact", title="T", summary="S")
    service = _make_service_mock()

    approve(tmp_path, proposal.id, service=service)

    assert list_pending(tmp_path) == []
    assert get(tmp_path, proposal.id) is None


def test_approve_calls_add_manual_memory(tmp_path: Path) -> None:
    proposal = stage(tmp_path, kind="invariant", title="Unique titles", summary="Titles must be unique")
    service = _make_service_mock()

    approve(tmp_path, proposal.id, service=service)

    service.add_manual_memory.assert_called_once()
    call_kwargs = service.add_manual_memory.call_args.kwargs
    assert call_kwargs["kind"] == MemoryKind.INVARIANT
    assert call_kwargs["title"] == "Unique titles"
    assert call_kwargs["summary"] == "Titles must be unique"


def test_approve_writes_audit_record(tmp_path: Path) -> None:
    proposal = stage(tmp_path, kind="doc_fact", title="T", summary="S")
    service = _make_service_mock(memory_id="mem-audit-001")

    record = approve(tmp_path, proposal.id, service=service)

    assert record.decision == "approved"
    assert record.proposal_id == proposal.id
    assert record.memory_id == "mem-audit-001"

    audit = list_audit(tmp_path)
    assert len(audit) == 1
    assert audit[0].decision == "approved"


# ---------------------------------------------------------------------------
# 4. reject → dropped from queue; audit trail kept
# ---------------------------------------------------------------------------


def test_reject_removes_from_queue(tmp_path: Path) -> None:
    proposal = stage(tmp_path, kind="doc_fact", title="T", summary="S")
    reject(tmp_path, proposal.id, reason="Not accurate enough")

    assert list_pending(tmp_path) == []
    assert get(tmp_path, proposal.id) is None


def test_reject_writes_audit_record_with_reason(tmp_path: Path) -> None:
    proposal = stage(tmp_path, kind="doc_fact", title="T", summary="S")
    record = reject(tmp_path, proposal.id, reason="Out of scope for now")

    assert record.decision == "rejected"
    assert record.reason == "Out of scope for now"
    assert record.proposal_id == proposal.id

    audit = list_audit(tmp_path)
    assert len(audit) == 1
    assert audit[0].reason == "Out of scope for now"


def test_reject_without_reason_still_writes_audit(tmp_path: Path) -> None:
    proposal = stage(tmp_path, kind="doc_fact", title="T", summary="S")
    record = reject(tmp_path, proposal.id)

    assert record.decision == "rejected"
    assert record.reason == ""


# ---------------------------------------------------------------------------
# 5. Deterministic ids
# ---------------------------------------------------------------------------


def test_ids_are_deterministic_for_same_content_and_seq(tmp_path: Path) -> None:
    p1 = stage(tmp_path, kind="doc_fact", title="Same", summary="Same summary")
    # Use a second repo root so seq also resets to 0.
    tmp2 = tmp_path / "repo2"
    tmp2.mkdir()
    p2 = stage(tmp2, kind="doc_fact", title="Same", summary="Same summary")
    assert p1.id == p2.id  # same content + seq=0 → same id


def test_ids_differ_when_seq_differs(tmp_path: Path) -> None:
    p1 = stage(tmp_path, kind="doc_fact", title="T", summary="S")  # seq=0
    p2 = stage(tmp_path, kind="doc_fact", title="T", summary="S")  # seq=1
    assert p1.id != p2.id


def test_ids_differ_when_content_differs(tmp_path: Path) -> None:
    p1 = stage(tmp_path, kind="doc_fact", title="Title A", summary="S")
    p2 = stage(tmp_path, kind="doc_fact", title="Title B", summary="S")
    assert p1.id != p2.id


# ---------------------------------------------------------------------------
# 6. Approve / reject unknown id → graceful error
# ---------------------------------------------------------------------------


def test_approve_unknown_id_raises_lookup_error(tmp_path: Path) -> None:
    service = _make_service_mock()
    with pytest.raises(LookupError, match="ms-unknown-0000"):
        approve(tmp_path, "ms-unknown-0000", service=service)


def test_reject_unknown_id_raises_lookup_error(tmp_path: Path) -> None:
    with pytest.raises(LookupError, match="ms-unknown-9999"):
        reject(tmp_path, "ms-unknown-9999")


# ---------------------------------------------------------------------------
# 7. --json envelopes
# ---------------------------------------------------------------------------


def test_list_json_envelope(tmp_path: Path) -> None:
    stage(tmp_path, kind="doc_fact", title="A", summary="Alpha")
    stage(tmp_path, kind="decision", title="B", summary="Beta")

    proposals = list_pending(tmp_path)
    payload = [
        {
            "id": p.id,
            "kind": p.kind,
            "title": p.title,
            "summary": p.summary,
            "reason": p.reason,
            "staged_at": p.staged_at,
            "seq": p.seq,
        }
        for p in proposals
    ]
    serialised = json.dumps(payload)
    loaded = json.loads(serialised)
    assert len(loaded) == 2
    assert loaded[0]["kind"] == "doc_fact"
    assert loaded[1]["kind"] == "decision"


def test_audit_record_json_serialisable(tmp_path: Path) -> None:
    proposal = stage(tmp_path, kind="doc_fact", title="T", summary="S")
    record = reject(tmp_path, proposal.id, reason="nope")

    serialised = json.dumps(record.to_dict())
    loaded = json.loads(serialised)
    assert loaded["decision"] == "rejected"
    assert loaded["reason"] == "nope"
    assert loaded["proposal_id"] == proposal.id


# ---------------------------------------------------------------------------
# 8. Empty queue is graceful
# ---------------------------------------------------------------------------


def test_empty_queue_returns_empty_list(tmp_path: Path) -> None:
    assert list_pending(tmp_path) == []


def test_empty_audit_returns_empty_list(tmp_path: Path) -> None:
    assert list_audit(tmp_path) == []


def test_get_nonexistent_proposal_returns_none(tmp_path: Path) -> None:
    assert get(tmp_path, "ms-does-not-exist-0000") is None


# ---------------------------------------------------------------------------
# 9. stage validation
# ---------------------------------------------------------------------------


def test_stage_rejects_empty_summary(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="summary"):
        stage(tmp_path, kind="doc_fact", title="T", summary="   ")


def test_stage_rejects_empty_title(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="title"):
        stage(tmp_path, kind="doc_fact", title="   ", summary="S")


def test_stage_rejects_empty_kind(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="kind"):
        stage(tmp_path, kind="   ", title="T", summary="S")


# ---------------------------------------------------------------------------
# 10. Mixed approve/reject audit sequence is monotonic
# ---------------------------------------------------------------------------


def test_audit_sequence_is_monotonic(tmp_path: Path) -> None:
    p1 = stage(tmp_path, kind="doc_fact", title="A", summary="Alpha")
    p2 = stage(tmp_path, kind="decision", title="B", summary="Beta")
    p3 = stage(tmp_path, kind="invariant", title="C", summary="Gamma")

    service = _make_service_mock()
    approve(tmp_path, p1.id, service=service)
    reject(tmp_path, p2.id, reason="wrong")
    approve(tmp_path, p3.id, service=service)

    audit = list_audit(tmp_path)
    assert len(audit) == 3
    seqs = [r.seq for r in audit]
    assert seqs == sorted(seqs), "audit sequence must be monotonically increasing"
    decisions = [r.decision for r in audit]
    assert decisions == ["approved", "rejected", "approved"]


# ---------------------------------------------------------------------------
# 11. CLI surface
# ---------------------------------------------------------------------------


def test_cli_add_stages_proposal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    result = runner.invoke(
        app,
        ["memstage", "add", "My proposed memory"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "staged" in result.output


def test_cli_add_json_returns_valid_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    result = runner.invoke(
        app,
        ["memstage", "add", "JSON memory proposal", "--json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "id" in payload
    assert payload["id"].startswith("ms-")
    assert "kind" in payload
    assert "title" in payload


def test_cli_list_empty_is_graceful(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    result = runner.invoke(app, ["memstage", "list"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "empty" in result.output.lower()


def test_cli_list_json_shows_staged_proposals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    # Stage via the queue core directly so we control the path.
    stage(tmp_path, kind="gotcha", title="T1", summary="S1")
    result = runner.invoke(app, ["memstage", "list", "--json"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    items = json.loads(result.output)
    assert isinstance(items, list)
    assert len(items) == 1
    assert items[0]["kind"] == "gotcha"


def test_cli_diff_renders_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    proposal = stage(tmp_path, kind="doc_fact", title="Diff test title", summary="Diff test summary")
    result = runner.invoke(app, ["memstage", "diff", proposal.id], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "+kind:" in result.output
    assert "+title:   Diff test title" in result.output


def test_cli_diff_unknown_id_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    result = runner.invoke(app, ["memstage", "diff", "ms-does-not-exist-9999"])
    assert result.exit_code == 1


def test_cli_reject_removes_from_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    proposal = stage(tmp_path, kind="doc_fact", title="T", summary="S")
    result = runner.invoke(
        app,
        ["memstage", "reject", proposal.id, "--reason", "not needed"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "rejected" in result.output


def test_cli_reject_unknown_id_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    result = runner.invoke(app, ["memstage", "reject", "ms-unknown-0000"])
    assert result.exit_code == 1


def test_cli_approve_unknown_id_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """approve with unknown id → exit 1 (no service needed to surface this)."""
    monkeypatch.chdir(tmp_path)
    app = _app()
    # Patch approve at the commands module level to avoid OnmcService init.
    with patch(
        "oh_no_my_claudecode.memstage.commands.approve"
    ) as mock_approve:
        mock_approve.side_effect = LookupError("no pending proposal with id 'ms-unknown-0000'")
        result = runner.invoke(app, ["memstage", "approve", "ms-unknown-0000"])
    assert result.exit_code == 1
    assert "error:" in result.output
