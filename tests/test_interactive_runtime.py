"""Interactive Claude Code runtime: mission arming and verified Stop control."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from oh_no_my_claudecode.hooks.installer import (
    DECISION_INTERCEPT_COMMAND,
    RUNTIME_STOP_COMMAND,
    install_wrap_hooks,
    wrap_hooks_installed,
)
from oh_no_my_claudecode.wrap.logic import compile_decision_intercept
from oh_no_my_claudecode.wrap.runtime import (
    MissionStatus,
    arm_mission,
    evaluate_completion,
    load_mission,
    prompt_is_coding_work,
)

_NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


def test_actionable_prompt_arms_strict_mission(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    mission = arm_mission(
        tmp_path,
        "session-1",
        "Fix the failing authentication test",
        strict=True,
        now=_NOW,
        fingerprint_reader=lambda _root: "baseline",
    )

    assert mission is not None
    assert mission.verifier == "pytest"
    assert mission.status is MissionStatus.ACTIVE
    assert load_mission(tmp_path, "session-1") == mission


def test_non_coding_and_soft_prompts_do_not_arm(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    assert not prompt_is_coding_work("Explain how authentication works")
    assert (
        arm_mission(
            tmp_path,
            "session-1",
            "Explain how authentication works",
            strict=True,
            fingerprint_reader=lambda _root: "baseline",
        )
        is None
    )
    assert (
        arm_mission(
            tmp_path,
            "session-2",
            "Fix the authentication bug",
            strict=False,
            fingerprint_reader=lambda _root: "baseline",
        )
        is None
    )


def test_product_feature_prompt_is_recognized_as_coding_work() -> None:
    assert prompt_is_coding_work("Implement a payment gateway")
    assert prompt_is_coding_work("Fix login")


def test_stop_blocks_without_a_non_vacuous_change(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    arm_mission(
        tmp_path,
        "session-1",
        "Fix the authentication bug",
        strict=True,
        now=_NOW,
        fingerprint_reader=lambda _root: "same",
    )

    decision = evaluate_completion(
        tmp_path,
        "session-1",
        strict=True,
        now=_NOW + timedelta(minutes=1),
        fingerprint_reader=lambda _root: "same",
        verifier_runner=lambda _command, _root: (True, "should not run"),
    )

    assert decision is not None
    assert decision.block is True
    assert "No repository change" in decision.reason
    assert json.loads(decision.hook_output())["decision"] == "block"
    assert load_mission(tmp_path, "session-1").blocks_used == 1  # type: ignore[union-attr]


def test_stop_blocks_on_failed_verifier_then_allows_verified_result(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    arm_mission(
        tmp_path,
        "session-1",
        "Fix the authentication bug",
        strict=True,
        now=_NOW,
        fingerprint_reader=lambda _root: "baseline",
    )

    failed = evaluate_completion(
        tmp_path,
        "session-1",
        strict=True,
        now=_NOW + timedelta(minutes=1),
        fingerprint_reader=lambda _root: "changed",
        verifier_runner=lambda _command, _root: (False, "1 failed"),
    )
    assert failed is not None and failed.block
    assert "1 failed" in failed.reason

    passed = evaluate_completion(
        tmp_path,
        "session-1",
        strict=True,
        now=_NOW + timedelta(minutes=2),
        fingerprint_reader=lambda _root: "changed-again",
        verifier_runner=lambda _command, _root: (True, "12 passed"),
    )
    assert passed is not None
    assert passed.block is False
    assert passed.status is MissionStatus.VERIFIED
    assert load_mission(tmp_path, "session-1").status is MissionStatus.VERIFIED  # type: ignore[union-attr]


def test_runtime_exhaustion_returns_control_to_user(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    arm_mission(
        tmp_path,
        "session-1",
        "Fix the authentication bug",
        strict=True,
        now=_NOW,
        fingerprint_reader=lambda _root: "baseline",
    )

    decision = None
    for attempt in range(7):
        decision = evaluate_completion(
            tmp_path,
            "session-1",
            strict=True,
            now=_NOW + timedelta(minutes=attempt + 1),
            fingerprint_reader=lambda _root: "changed",
            verifier_runner=lambda _command, _root: (False, "still failing"),
        )

    assert decision is not None
    assert decision.block is False
    assert decision.status is MissionStatus.EXHAUSTED
    assert "budget exhausted" in decision.reason


def test_low_risk_question_uses_recommended_default() -> None:
    payload = {
        "tool_name": "AskUserQuestion",
        "tool_input": {
            "questions": [
                {
                    "question": "Which cache library?",
                    "options": [
                        {"label": "Existing cache", "description": "Recommended; already used"},
                        {"label": "New dependency", "description": "Add another package"},
                    ],
                }
            ]
        },
    }

    output = json.loads(compile_decision_intercept(payload, strict=True))
    hook = output["hookSpecificOutput"]
    assert hook["permissionDecision"] == "deny"
    assert "Existing cache" in hook["permissionDecisionReason"]


def test_material_risk_question_still_reaches_user() -> None:
    payload = {
        "tool_name": "AskUserQuestion",
        "tool_input": {
            "questions": [
                {
                    "question": "Which production payment migration should run?",
                    "options": [{"label": "Immediate"}, {"label": "Staged"}],
                }
            ]
        },
    }
    assert compile_decision_intercept(payload, strict=True) == ""


def test_wrap_installs_runtime_hooks_idempotently(tmp_path: Path) -> None:
    settings = tmp_path / ".claude" / "settings.json"
    backup = tmp_path / ".claude" / "settings.json.onmc-backup"
    install_wrap_hooks(
        repo_root=tmp_path,
        strict=True,
        settings_path=settings,
        backup_path=backup,
    )
    install_wrap_hooks(
        repo_root=tmp_path,
        strict=True,
        settings_path=settings,
        backup_path=backup,
    )

    payload = json.loads(settings.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    assert serialized.count(DECISION_INTERCEPT_COMMAND) == 1
    assert serialized.count(RUNTIME_STOP_COMMAND) == 1
    assert wrap_hooks_installed(settings_path=settings)
