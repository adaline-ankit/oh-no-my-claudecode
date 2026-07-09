"""Tests for the ``onmc approve`` executor — the phone-to-merge loop closer.

All offline and deterministic.  The pure decision core (:func:`plan_approval`)
is hammered by constructing :class:`MissionCard` / :class:`UnitLine` directly;
the CLI is exercised via ``CliRunner`` over a seeded on-disk swarm (manifest +
receipts) with the real merger monkeypatched to a fake — never touching
git / gh / network.  No Rich ``--help`` output is scraped.

Coverage
--------
plan_approval (pure):
 1. "approve all" -> only verified units eligible; held/unverified/aborted
    refused with the correct reason.
 2. "approve unit 2" -> that unit when verified.
 3. "approve unit 3" (held) -> refused, NEVER eligible.
 4. an unverified (receipt-less) target -> refused, NEVER eligible.
 5. a not-found target -> refused with not-found.
 6. an aborted unit -> refused with aborted.
 7. SHOW_DIFF / ABORT / UNKNOWN -> no merges, explanatory note.
 8. determinism (same inputs -> equal plan).
execute_plan (thin):
 9. dry run NEVER calls the merger and records intent per eligible unit.
10. execute (dry_run=False) calls the injected merger exactly for eligible
    units and skips refused ones.
CLI (CliRunner):
11. dry plan exit 0 + DRY banner.
12. --execute with an injected fake merger merges eligible units.
13. a refused per-unit target exits non-zero.
14. --json envelope shape.
15. outside an onmc repo -> exit 1 cleanly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from oh_no_my_claudecode.approve.executor import (
    REASON_ABORTED,
    REASON_HELD,
    REASON_NOT_FOUND,
    REASON_UNVERIFIED,
    MergeOutcome,
    execute_plan,
    plan_approval,
)
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.missionbridge.approve import parse_action
from oh_no_my_claudecode.missionbridge.models import (
    ApproveAction,
    ApproveKind,
    MissionCard,
    UnitLine,
)

# ---------------------------------------------------------------------------
# Pure fixtures — construct UnitLine / MissionCard directly.
# ---------------------------------------------------------------------------


def _verified(unit_id: str, *, pr_url: str = "") -> UnitLine:
    return UnitLine(
        unit_id=unit_id,
        goal=f"goal {unit_id}",
        status="done",
        verified=True,
        held=False,
        receipt_hash="cafef00d",
        diff_sha="deadbeef",
        pr_url=pr_url,
    )


def _held(unit_id: str) -> UnitLine:
    """Held: has a receipt but the manifest did not mark it verified."""
    return UnitLine(
        unit_id=unit_id,
        goal=f"goal {unit_id}",
        status="done",
        verified=False,
        held=True,
        receipt_hash="beadfeed",
        detail="held, not shipped",
    )


def _unverified(unit_id: str) -> UnitLine:
    """Unverified: no tamper-evident receipt at all."""
    return UnitLine(
        unit_id=unit_id,
        goal=f"goal {unit_id}",
        status="done",
        verified=False,
        held=True,
        receipt_hash=None,
        detail="held, not shipped",
    )


def _aborted(unit_id: str) -> UnitLine:
    return UnitLine(
        unit_id=unit_id,
        goal=f"goal {unit_id}",
        status="aborted",
        verified=False,
        held=True,
        receipt_hash=None,
    )


def _card() -> MissionCard:
    """A mixed card: 2 verified, 1 held, 1 unverified, 1 aborted."""
    return MissionCard(
        mission_id="sw-1",
        goal="ship the thing",
        units=[
            _verified("unit-0001", pr_url="https://example.test/pull/11"),
            _verified("unit-0002", pr_url="https://example.test/pull/12"),
            _held("unit-0003"),
            _unverified("unit-0004"),
            _aborted("unit-0005"),
        ],
    )


# ---------------------------------------------------------------------------
# plan_approval
# ---------------------------------------------------------------------------


def test_approve_all_only_verified_eligible() -> None:
    plan = plan_approval(_card(), parse_action("approve all"))
    assert plan.kind is ApproveKind.APPROVE_ALL
    assert plan.eligible == ["unit-0001", "unit-0002"]
    refused = dict(plan.refused)
    assert refused == {
        "unit-0003": REASON_HELD,
        "unit-0004": REASON_UNVERIFIED,
        "unit-0005": REASON_ABORTED,
    }


def test_approve_unit_verified_is_eligible() -> None:
    plan = plan_approval(_card(), parse_action("approve unit 2"))
    assert plan.kind is ApproveKind.APPROVE_UNIT
    assert plan.eligible == ["unit-0002"]
    assert plan.refused == []


def test_approve_held_unit_never_eligible() -> None:
    plan = plan_approval(_card(), parse_action("approve unit 3"))
    assert plan.eligible == []
    assert plan.refused == [("unit-0003", REASON_HELD)]


def test_approve_unverified_unit_never_eligible() -> None:
    plan = plan_approval(_card(), parse_action("approve unit 4"))
    assert plan.eligible == []
    assert plan.refused == [("unit-0004", REASON_UNVERIFIED)]


def test_approve_aborted_unit_refused_with_aborted_reason() -> None:
    plan = plan_approval(_card(), parse_action("approve unit 5"))
    assert plan.eligible == []
    assert plan.refused == [("unit-0005", REASON_ABORTED)]


def test_approve_unknown_unit_is_not_found() -> None:
    plan = plan_approval(_card(), parse_action("approve unit 99"))
    assert plan.eligible == []
    assert plan.refused == [("unit-0099", REASON_NOT_FOUND)]


def test_show_diff_abort_unknown_never_merge() -> None:
    card = _card()
    for message in ("show diff unit 1", "abort", "wat is this"):
        plan = plan_approval(card, parse_action(message))
        assert plan.eligible == []
        assert plan.refused == []
        assert plan.note  # an explanatory note is always present


def test_show_diff_kind_and_abort_kind() -> None:
    card = _card()
    assert plan_approval(card, parse_action("show diff unit 1")).kind is ApproveKind.SHOW_DIFF
    assert plan_approval(card, parse_action("abort")).kind is ApproveKind.ABORT
    assert plan_approval(card, ApproveAction(ApproveKind.UNKNOWN)).kind is ApproveKind.UNKNOWN


def test_plan_is_deterministic() -> None:
    card = _card()
    action = parse_action("approve all")
    assert plan_approval(card, action) == plan_approval(card, action)


def test_empty_card_approve_all_has_nothing() -> None:
    plan = plan_approval(MissionCard(mission_id="empty", goal=""), parse_action("approve all"))
    assert plan.eligible == []
    assert plan.refused == []


# ---------------------------------------------------------------------------
# execute_plan
# ---------------------------------------------------------------------------


class _RecordingMerger:
    """A fake merger that records the unit ids it was asked to merge."""

    def __init__(self, *, ok: bool = True) -> None:
        self.calls: list[str] = []
        self._ok = ok

    def __call__(self, repo_root: Path, swarm_id: str, unit_id: str) -> MergeOutcome:
        self.calls.append(unit_id)
        return MergeOutcome(unit_id, ok=self._ok, detail="merged (fake)")


def test_execute_dry_never_calls_merger() -> None:
    plan = plan_approval(_card(), parse_action("approve all"))
    merger = _RecordingMerger()
    result = execute_plan(Path("/repo"), "sw-1", plan, merger=merger, dry_run=True)

    assert merger.calls == []  # the merger was never invoked in a dry run
    assert result.dry_run is True
    assert [o.unit_id for o in result.merged] == ["unit-0001", "unit-0002"]
    assert all(o.ok and "dry-run" in o.detail for o in result.merged)
    assert result.skipped == plan.refused


def test_execute_calls_merger_for_eligible_only() -> None:
    plan = plan_approval(_card(), parse_action("approve all"))
    merger = _RecordingMerger()
    result = execute_plan(Path("/repo"), "sw-1", plan, merger=merger, dry_run=False)

    # Called exactly once per eligible unit, never for refused ones.
    assert merger.calls == ["unit-0001", "unit-0002"]
    assert result.dry_run is False
    assert [o.unit_id for o in result.merged] == ["unit-0001", "unit-0002"]
    assert all(o.ok for o in result.merged)
    # Refused units are reported, never merged.
    assert dict(result.skipped) == {
        "unit-0003": REASON_HELD,
        "unit-0004": REASON_UNVERIFIED,
        "unit-0005": REASON_ABORTED,
    }
    assert not any(uid in merger.calls for uid in ("unit-0003", "unit-0004", "unit-0005"))


def test_execute_default_merger_is_dry_safe() -> None:
    """execute_plan(dry_run=False) with no merger still performs no real action."""
    plan = plan_approval(_card(), parse_action("approve unit 1"))
    result = execute_plan(Path("/repo"), "sw-1", plan, dry_run=False)
    assert [o.unit_id for o in result.merged] == ["unit-0001"]
    assert all("dry-run" in o.detail for o in result.merged)


# ---------------------------------------------------------------------------
# CLI (CliRunner) — seed an on-disk swarm so build_card runs end-to-end.
# ---------------------------------------------------------------------------


def _write_receipt(
    repo: Path,
    name: str,
    *,
    verified: bool = True,
    receipt_hash: str = "cafef00d1234",
    pr_url: str | None = None,
) -> None:
    receipts = repo / ".agent-memory" / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "verified": verified,
        "diff_sha": "aaa111",
        "receipt_hash": receipt_hash,
        "cost_usd": 0.25,
    }
    if pr_url is not None:
        payload["pr_url"] = pr_url
    (receipts / name).write_text(json.dumps(payload), encoding="utf-8")


def _seed_swarm(repo: Path, swarm_id: str = "sw-1") -> None:
    """One verified unit (with PR) + one held unit (no receipt)."""
    (repo / ".git").mkdir(exist_ok=True)
    _write_receipt(repo, "run-a.json", pr_url="https://example.test/pull/11")
    swarm_dir = repo / ".onmc" / "swarm" / swarm_id
    swarm_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "swarm_id": swarm_id,
        "units": {
            "unit-0001": {
                "goal": "add feature A",
                "status": "done",
                "verified": True,
                "receipt_path": ".agent-memory/receipts/run-a.json",
            },
            "unit-0002": {
                "goal": "broken feature B",
                "status": "failed",
                "verified": False,
                "error": "verifier failed",
            },
        },
    }
    (swarm_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_cli_dry_plan_exit_zero(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_swarm(tmp_path)
    result = CliRunner().invoke(app, ["approve", "sw-1", "approve all"])
    assert result.exit_code == 0
    assert "DRY" in result.stdout
    assert "unit-0001" in result.stdout
    # The held unit is reported as refused, never merged.
    assert "unit-0002" in result.stdout


def test_cli_execute_with_fake_merger(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_swarm(tmp_path)
    merger = _RecordingMerger()
    monkeypatch.setattr(
        "oh_no_my_claudecode.approve.commands._build_merger", lambda: merger
    )
    result = CliRunner().invoke(app, ["approve", "sw-1", "approve all", "--execute"])
    assert result.exit_code == 0
    assert merger.calls == ["unit-0001"]  # only the verified unit


def test_cli_refused_target_exits_nonzero(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_swarm(tmp_path)
    result = CliRunner().invoke(app, ["approve", "sw-1", "approve unit 2"])
    assert result.exit_code != 0
    assert "unit-0002" in result.stdout


def test_cli_json_shape(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_swarm(tmp_path)
    result = CliRunner().invoke(app, ["approve", "sw-1", "approve all", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["kind"] == "approve_result"
    assert payload["action"] == str(ApproveKind.APPROVE_ALL)
    assert payload["dry_run"] is True
    assert payload["eligible"] == ["unit-0001"]
    assert payload["refused"] == [{"unit_id": "unit-0002", "reason": REASON_UNVERIFIED}]


def test_cli_outside_repo_exits_one(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # no .git anywhere -> not an onmc repo
    result = CliRunner().invoke(app, ["approve", "sw-1", "approve all"])
    assert result.exit_code == 1
