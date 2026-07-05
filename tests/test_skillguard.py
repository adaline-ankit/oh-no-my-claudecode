"""Tests for the ``onmc skillguard`` skill write-approval staging queue.

Covers the pure queue core (deterministic, dependency-injected) and the
auto-discovered CLI surface (exercised via flags + JSON / exit codes only —
never by asserting Rich ``--help`` text).

What is verified
----------------
- stage -> appears in list_pending; does NOT touch the skill store
- diff renders a unified-diff with the proposed content as additions (create op)
- diff renders correct before/after for edit op
- approve -> proposal removed from queue; applies via real skill path; audit trail
- reject -> proposal dropped from queue; audit trail kept
- deterministic ids (same content + seq -> same id; different seq -> different id)
- approve with unknown id -> graceful LookupError
- reject with unknown id -> graceful LookupError
- ``--json`` envelopes are valid JSON with expected keys
- empty queue is graceful (no crash, empty list)
- audit sequence is monotonic across mixed approve/reject calls
- delete proposal: approve removes skill from store
- ``--content-file`` flag reads content from file
- CLI: stage, list, diff, approve, reject surface -- reachable and correct
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from oh_no_my_claudecode.skillguard.commands import register
from oh_no_my_claudecode.skillguard.queue import (
    SkillAuditRecord,
    approve,
    diff,
    get,
    list_audit,
    list_pending,
    reject,
    stage,
)

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service_mock() -> MagicMock:
    """A mock OnmcService -- skillguard calls storage directly, not via service."""
    from oh_no_my_claudecode.core.service import OnmcService  # noqa: PLC0415

    return MagicMock(spec=OnmcService)


def _app() -> typer.Typer:
    """Fresh Typer app with skillguard registered."""
    app = typer.Typer()

    @app.command("__sentinel__")
    def _sentinel() -> None:  # pragma: no cover
        ...

    register(app)
    return app


# ---------------------------------------------------------------------------
# 1. stage -> appears in list_pending; does NOT affect skill store
# ---------------------------------------------------------------------------


def test_stage_appears_in_list_pending(tmp_path: Path) -> None:
    proposal = stage(
        tmp_path,
        op="create",
        name="my-skill",
        content="Always use uv instead of pip",
        reason="team convention",
    )
    assert proposal.id.startswith("sg-")
    assert proposal.op == "create"
    assert proposal.name == "my-skill"

    pending = list_pending(tmp_path)
    assert len(pending) == 1
    assert pending[0].id == proposal.id


def test_stage_does_not_write_to_skill_store(tmp_path: Path) -> None:
    """Staging a proposal must NOT create or modify the SQLite skill store."""
    stage(
        tmp_path,
        op="create",
        name="never-written",
        content="Should not be in skill store",
    )
    db_path = tmp_path / ".onmc" / "memory.db"
    assert not db_path.exists()


def test_stage_persisted_under_onmc_skillguard(tmp_path: Path) -> None:
    proposal = stage(tmp_path, op="create", name="stored-skill", content="Body text")
    expected = tmp_path / ".onmc" / "skillguard" / "pending" / f"{proposal.id}.json"
    assert expected.is_file()


def test_stage_delete_allows_empty_content(tmp_path: Path) -> None:
    """Delete proposals may have empty content."""
    proposal = stage(tmp_path, op="delete", name="old-skill", content="")
    assert proposal.op == "delete"
    assert proposal.content == ""
    assert len(list_pending(tmp_path)) == 1


# ---------------------------------------------------------------------------
# 2. diff renders unified-diff with proposed content as additions (create)
# ---------------------------------------------------------------------------


def test_diff_create_renders_additions(tmp_path: Path) -> None:
    proposal = stage(
        tmp_path,
        op="create",
        name="diff-skill",
        content="Line one of skill\nLine two of skill",
    )
    output = diff(tmp_path, proposal.id)
    assert "+Line one of skill" in output
    assert "+Line two of skill" in output
    assert "op: create" in output


def test_diff_edit_renders_additions(tmp_path: Path) -> None:
    """Edit diff shows proposed lines as additions (baseline empty since skill not in store)."""
    proposal = stage(
        tmp_path,
        op="edit",
        name="edit-skill",
        content="New body text",
    )
    output = diff(tmp_path, proposal.id)
    assert "op: edit" in output
    assert "+New body text" in output


def test_diff_delete_renders_removal_header(tmp_path: Path) -> None:
    proposal = stage(tmp_path, op="delete", name="to-delete", content="")
    output = diff(tmp_path, proposal.id)
    assert "op: delete" in output


def test_diff_unknown_id_returns_error_string(tmp_path: Path) -> None:
    output = diff(tmp_path, "sg-nonexistent-0000")
    assert output.startswith("error:")
    assert "sg-nonexistent-0000" in output


def test_diff_includes_reason_when_set(tmp_path: Path) -> None:
    proposal = stage(
        tmp_path,
        op="create",
        name="reason-skill",
        content="Body",
        reason="Saved 3 hours debugging",
    )
    output = diff(tmp_path, proposal.id)
    assert "Saved 3 hours debugging" in output


# ---------------------------------------------------------------------------
# 3. approve -> removes from queue; applies to skill store; audit trail
# ---------------------------------------------------------------------------


def test_approve_removes_from_queue(tmp_path: Path) -> None:
    proposal = stage(tmp_path, op="create", name="approve-skill", content="Skill body")
    service = _make_service_mock()

    approve(tmp_path, proposal.id, service=service)

    assert list_pending(tmp_path) == []
    assert get(tmp_path, proposal.id) is None


def test_approve_writes_audit_record(tmp_path: Path) -> None:
    proposal = stage(tmp_path, op="create", name="audit-skill", content="Body")
    service = _make_service_mock()

    record = approve(tmp_path, proposal.id, service=service)

    assert record.decision == "approved"
    assert record.proposal_id == proposal.id

    audit = list_audit(tmp_path)
    assert len(audit) == 1
    assert audit[0].decision == "approved"


def test_approve_create_writes_skill_to_store(tmp_path: Path) -> None:
    """approve on a create proposal creates a real skill in the SQLite store."""
    proposal = stage(
        tmp_path,
        op="create",
        name="real-skill",
        content="Always prefer uv over pip",
    )
    service = _make_service_mock()

    record = approve(tmp_path, proposal.id, service=service)
    assert record.skill_id.startswith("sk-")

    from oh_no_my_claudecode.storage.sqlite import SQLiteStorage  # noqa: PLC0415

    db_path = tmp_path / ".onmc" / "memory.db"
    storage = SQLiteStorage(db_path)
    skills = storage.list_skills()
    skill_names = [sk.name for sk in skills]
    assert "real-skill" in skill_names


def test_approve_delete_removes_skill_from_store(tmp_path: Path) -> None:
    """approve on a delete proposal removes the skill from the SQLite store."""
    from datetime import UTC, datetime

    from oh_no_my_claudecode.models.skill import Skill  # noqa: PLC0415
    from oh_no_my_claudecode.storage.sqlite import SQLiteStorage  # noqa: PLC0415

    db_path = tmp_path / ".onmc" / "memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage = SQLiteStorage(db_path)
    storage.initialize()
    now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)
    existing = Skill(
        id="sk-to-delete",
        name="to-delete-skill",
        body="old body",
        trigger="trigger",
        tags=[],
        files=[],
        source_memory_ids=[],
        use_count=0,
        success_count=0,
        confidence=0.5,
        auto_inject=True,
        created_at=now,
        updated_at=now,
        last_used_at=None,
    )
    storage.add_skill(existing)

    proposal = stage(tmp_path, op="delete", name="to-delete-skill", content="")
    service = _make_service_mock()
    record = approve(tmp_path, proposal.id, service=service)

    assert record.decision == "approved"
    remaining = [sk.name for sk in storage.list_skills()]
    assert "to-delete-skill" not in remaining


# ---------------------------------------------------------------------------
# 4. reject -> dropped from queue; audit trail kept
# ---------------------------------------------------------------------------


def test_reject_removes_from_queue(tmp_path: Path) -> None:
    proposal = stage(tmp_path, op="create", name="reject-skill", content="Body")
    reject(tmp_path, proposal.id, reason="Not needed")

    assert list_pending(tmp_path) == []
    assert get(tmp_path, proposal.id) is None


def test_reject_writes_audit_record_with_reason(tmp_path: Path) -> None:
    proposal = stage(tmp_path, op="create", name="reject-reason-skill", content="Body")
    record = reject(tmp_path, proposal.id, reason="Out of scope")

    assert record.decision == "rejected"
    assert record.reason == "Out of scope"
    assert record.proposal_id == proposal.id

    audit = list_audit(tmp_path)
    assert len(audit) == 1
    assert audit[0].reason == "Out of scope"


def test_reject_without_reason_still_writes_audit(tmp_path: Path) -> None:
    proposal = stage(tmp_path, op="create", name="no-reason-skill", content="Body")
    record = reject(tmp_path, proposal.id)

    assert record.decision == "rejected"
    assert record.reason == ""


# ---------------------------------------------------------------------------
# 5. Deterministic ids
# ---------------------------------------------------------------------------


def test_ids_are_deterministic_for_same_content_and_seq(tmp_path: Path) -> None:
    p1 = stage(tmp_path, op="create", name="Same", content="Same body")
    tmp2 = tmp_path / "repo2"
    tmp2.mkdir()
    p2 = stage(tmp2, op="create", name="Same", content="Same body")
    assert p1.id == p2.id


def test_ids_differ_when_seq_differs(tmp_path: Path) -> None:
    p1 = stage(tmp_path, op="create", name="T", content="S")  # seq=0
    p2 = stage(tmp_path, op="create", name="T", content="S")  # seq=1
    assert p1.id != p2.id


def test_ids_differ_when_content_differs(tmp_path: Path) -> None:
    p1 = stage(tmp_path, op="create", name="Skill A", content="Body A")
    p2 = stage(tmp_path, op="create", name="Skill B", content="Body B")
    assert p1.id != p2.id


# ---------------------------------------------------------------------------
# 6. Approve / reject unknown id -> graceful error
# ---------------------------------------------------------------------------


def test_approve_unknown_id_raises_lookup_error(tmp_path: Path) -> None:
    service = _make_service_mock()
    with pytest.raises(LookupError, match="sg-unknown-0000"):
        approve(tmp_path, "sg-unknown-0000", service=service)


def test_reject_unknown_id_raises_lookup_error(tmp_path: Path) -> None:
    with pytest.raises(LookupError, match="sg-unknown-9999"):
        reject(tmp_path, "sg-unknown-9999")


# ---------------------------------------------------------------------------
# 7. --json envelopes
# ---------------------------------------------------------------------------


def test_list_json_envelope(tmp_path: Path) -> None:
    stage(tmp_path, op="create", name="Alpha", content="Alpha body")
    stage(tmp_path, op="edit", name="Beta", content="Beta body")

    proposals = list_pending(tmp_path)
    payload = [
        {
            "id": p.id,
            "op": p.op,
            "name": p.name,
            "content": p.content,
            "reason": p.reason,
            "staged_at": p.staged_at,
            "seq": p.seq,
        }
        for p in proposals
    ]
    serialised = json.dumps(payload)
    loaded = json.loads(serialised)
    assert len(loaded) == 2
    assert loaded[0]["op"] == "create"
    assert loaded[1]["op"] == "edit"


def test_audit_record_json_serialisable(tmp_path: Path) -> None:
    proposal = stage(tmp_path, op="create", name="json-audit", content="Body")
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
    assert get(tmp_path, "sg-does-not-exist-0000") is None


# ---------------------------------------------------------------------------
# 9. stage validation
# ---------------------------------------------------------------------------


def test_stage_rejects_empty_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="name"):
        stage(tmp_path, op="create", name="   ", content="Body")


def test_stage_rejects_invalid_op(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="op"):
        stage(tmp_path, op="upsert", name="skill", content="Body")


def test_stage_rejects_empty_content_for_create(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="content"):
        stage(tmp_path, op="create", name="skill", content="   ")


# ---------------------------------------------------------------------------
# 10. Monotonic audit sequence across mixed approve/reject
# ---------------------------------------------------------------------------


def test_audit_sequence_is_monotonic(tmp_path: Path) -> None:
    p1 = stage(tmp_path, op="create", name="A", content="Alpha")
    p2 = stage(tmp_path, op="create", name="B", content="Beta")
    p3 = stage(tmp_path, op="create", name="C", content="Gamma")

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


def test_cli_stage_creates_proposal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    result = runner.invoke(
        app,
        [
            "skillguard", "stage", "--name", "my-skill", "--op", "create",
            "--content", "Do the thing always",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "staged" in result.output


def test_cli_stage_json_returns_valid_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    result = runner.invoke(
        app,
        [
            "skillguard", "stage", "--name", "json-skill", "--op", "create",
            "--content", "JSON skill body", "--json",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "id" in payload
    assert payload["id"].startswith("sg-")
    assert "op" in payload
    assert "name" in payload


def test_cli_stage_content_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    content_file = tmp_path / "skill.md"
    content_file.write_text("Content from file\nLine two", encoding="utf-8")
    app = _app()
    result = runner.invoke(
        app,
        [
            "skillguard", "stage", "--name", "file-skill", "--op", "create",
            "--content-file", str(content_file),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "staged" in result.output
    pending = list_pending(tmp_path)
    assert len(pending) == 1
    assert "Content from file" in pending[0].content


def test_cli_list_empty_is_graceful(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    result = runner.invoke(app, ["skillguard", "list"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "empty" in result.output.lower()


def test_cli_list_json_shows_staged_proposals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    stage(tmp_path, op="edit", name="list-test-skill", content="Edited body")
    result = runner.invoke(app, ["skillguard", "list", "--json"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    items = json.loads(result.output)
    assert isinstance(items, list)
    assert len(items) == 1
    assert items[0]["op"] == "edit"


def test_cli_diff_renders_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    proposal = stage(
        tmp_path, op="create", name="diff-cli-skill", content="Diff CLI content line"
    )
    result = runner.invoke(app, ["skillguard", "diff", proposal.id], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "+Diff CLI content line" in result.output


def test_cli_diff_unknown_id_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    result = runner.invoke(app, ["skillguard", "diff", "sg-does-not-exist-9999"])
    assert result.exit_code == 1


def test_cli_reject_removes_from_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    proposal = stage(tmp_path, op="create", name="reject-cli-skill", content="Body")
    result = runner.invoke(
        app,
        ["skillguard", "reject", proposal.id, "--reason", "not needed"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "rejected" in result.output


def test_cli_reject_unknown_id_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    result = runner.invoke(app, ["skillguard", "reject", "sg-unknown-0000"])
    assert result.exit_code == 1


def test_cli_approve_unknown_id_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """approve with unknown id -> exit 1."""
    monkeypatch.chdir(tmp_path)
    app = _app()
    with patch("oh_no_my_claudecode.skillguard.commands.approve") as mock_approve:
        mock_approve.side_effect = LookupError("no pending proposal with id 'sg-unknown-0000'")
        result = runner.invoke(app, ["skillguard", "approve", "sg-unknown-0000"])
    assert result.exit_code == 1
    assert "error:" in result.output


def test_cli_approve_json_returns_audit_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    proposal = stage(
        tmp_path, op="create", name="approve-json-skill", content="Approved body content"
    )
    with patch("oh_no_my_claudecode.skillguard.commands.approve") as mock_approve:
        mock_record = SkillAuditRecord(
            seq=0,
            proposal_id=proposal.id,
            decision="approved",
            skill_id="sk-abc123",
        )
        mock_approve.return_value = mock_record
        result = runner.invoke(
            app,
            ["skillguard", "approve", proposal.id, "--json"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["decision"] == "approved"
    assert payload["skill_id"] == "sk-abc123"
    assert "proposal_id" in payload
