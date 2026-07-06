"""Tests for onmc swarm auto-model routing: annotate_units_with_models.

All inputs are built in-memory — synthetic receipt dicts routed through the
flywheel's own :func:`summarize`, and fake unit lists shaped like the
inline-swarm unit dicts (``{"id": ..., "goal": ...}``).  No files, no clock,
no subprocess.  Also covers ``plan_inline_swarm(..., auto_model_report=...)``
end to end and confirms omitting it leaves units byte-for-byte unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.flywheel.analyze import FlywheelReport, summarize
from oh_no_my_claudecode.swarm.auto_model import (
    annotate_units_with_models,
    build_routing_summary_lines,
)
from oh_no_my_claudecode.swarm.inline import plan_inline_swarm

_FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _receipt(
    *, model: str, verified: bool, goal: str, cost_usd: float | None = 0.10
) -> dict[str, Any]:
    return {"model": model, "verified": verified, "goal": goal, "cost_usd": cost_usd,
            "wall_seconds": 30.0}


def _corpus() -> list[dict[str, Any]]:
    """opus reliably wins 'parser' goals (3/3); sonnet is the overall best."""
    receipts: list[dict[str, Any]] = []
    for _ in range(3):
        receipts.append(_receipt(model="opus", verified=True, goal="refactor the parser module"))
    receipts.append(_receipt(model="haiku", verified=False, goal="rewrite parser tokenizer"))
    for _ in range(5):
        receipts.append(_receipt(model="sonnet", verified=True, goal="polish the ui layout"))
    return receipts


# ---------------------------------------------------------------------------
# annotate_units_with_models — pure helper
# ---------------------------------------------------------------------------


def test_annotates_units_with_keyword_winner() -> None:
    report = summarize(_corpus())
    units = [{"id": "unit-0000", "goal": "improve the parser error handling"}]
    annotated = annotate_units_with_models(units, report)
    assert annotated[0]["suggested_model"] == "opus"
    assert annotated[0]["suggested_model_confidence"] == 1.0


def test_annotates_units_with_overall_best_when_no_keyword_matches() -> None:
    report = summarize(_corpus())
    units = [{"id": "unit-0000", "goal": "deploy the release pipeline widget"}]
    annotated = annotate_units_with_models(units, report)
    assert annotated[0]["suggested_model"] == "sonnet"
    assert 0.0 < annotated[0]["suggested_model_confidence"] <= 0.6


def test_low_data_goal_falls_back_to_default_model() -> None:
    """An empty/insufficient report yields the honest default at zero confidence."""
    report = summarize([])
    units = [{"id": "unit-0000", "goal": "something nobody has ever tried"}]
    annotated = annotate_units_with_models(units, report, default_model="sonnet")
    assert annotated[0]["suggested_model"] == "sonnet"
    assert annotated[0]["suggested_model_confidence"] == 0.0


def test_custom_default_model_is_respected() -> None:
    report = summarize([])
    units = [{"id": "unit-0000", "goal": "anything"}]
    annotated = annotate_units_with_models(units, report, default_model="haiku")
    assert annotated[0]["suggested_model"] == "haiku"


def test_preserves_all_original_unit_keys() -> None:
    report = summarize(_corpus())
    units = [{"id": "unit-0000", "goal": "refactor the parser module", "extra": "keep-me"}]
    annotated = annotate_units_with_models(units, report)
    assert annotated[0]["extra"] == "keep-me"
    assert annotated[0]["goal"] == "refactor the parser module"
    assert annotated[0]["id"] == "unit-0000"


def test_does_not_mutate_input_units() -> None:
    report = summarize(_corpus())
    units = [{"id": "unit-0000", "goal": "refactor the parser module"}]
    annotate_units_with_models(units, report)
    assert "suggested_model" not in units[0]


def test_multiple_units_each_get_their_own_suggestion() -> None:
    report = summarize(_corpus())
    units = [
        {"id": "unit-0000", "goal": "refactor the parser module"},
        {"id": "unit-0001", "goal": "polish the ui layout further"},
    ]
    annotated = annotate_units_with_models(units, report)
    assert annotated[0]["suggested_model"] == "opus"
    assert annotated[1]["suggested_model"] == "sonnet"


def test_missing_goal_key_does_not_raise() -> None:
    """A unit with no goal key tokenizes to nothing; with no evidence at all,
    this must be the honest insufficient-data default, not a fabricated pick.
    """
    report = summarize([])
    units: list[dict[str, Any]] = [{"id": "unit-0000"}]
    annotated = annotate_units_with_models(units, report)
    assert annotated[0]["suggested_model"] == "sonnet"
    assert annotated[0]["suggested_model_confidence"] == 0.0


def test_build_routing_summary_lines_format() -> None:
    units = [
        {"id": "unit-0000", "goal": "refactor the parser module",
         "suggested_model": "opus", "suggested_model_confidence": 1.0},
    ]
    lines = build_routing_summary_lines(units)
    assert len(lines) == 1
    assert "unit-0000" in lines[0]
    assert "opus" in lines[0]
    assert "refactor the parser module" in lines[0]


def test_build_routing_summary_lines_skips_unannotated_units() -> None:
    units = [{"id": "unit-0000", "goal": "no suggestion here"}]
    assert build_routing_summary_lines(units) == []


# ---------------------------------------------------------------------------
# plan_inline_swarm integration — additive, backward-compatible
# ---------------------------------------------------------------------------


def test_plan_inline_swarm_without_auto_model_report_is_unchanged(tmp_path: Path) -> None:
    """No auto_model_report -> units carry no suggested_model fields at all."""
    plan = plan_inline_swarm(
        tmp_path, ["refactor the parser module"], concurrency=1,
        swarm_id="nomodel1", now=_FIXED_NOW,
    )
    assert "suggested_model" not in plan["units"][0]

    import json

    manifest = json.loads(
        (tmp_path / ".onmc" / "swarm" / "nomodel1" / "manifest.json").read_text()
    )
    assert "suggested_model" not in manifest["units"]["unit-0000"]


def test_plan_inline_swarm_with_auto_model_report_annotates_manifest(tmp_path: Path) -> None:
    report = summarize(_corpus())
    plan = plan_inline_swarm(
        tmp_path, ["refactor the parser module"], concurrency=1,
        swarm_id="withmodel1", now=_FIXED_NOW, auto_model_report=report,
    )
    assert plan["units"][0]["suggested_model"] == "opus"

    import json

    manifest = json.loads(
        (tmp_path / ".onmc" / "swarm" / "withmodel1" / "manifest.json").read_text()
    )
    assert manifest["units"]["unit-0000"]["suggested_model"] == "opus"
    assert manifest["units"]["unit-0000"]["suggested_model_confidence"] == 1.0


def test_plan_inline_swarm_auto_model_low_data_fallback(tmp_path: Path) -> None:
    """Empty report -> every unit gets the honest default, not a fabricated pick."""
    empty_report = FlywheelReport(total=0, verified_total=0)
    plan = plan_inline_swarm(
        tmp_path, ["do something new"], concurrency=1,
        swarm_id="lowdata1", now=_FIXED_NOW, auto_model_report=empty_report,
    )
    assert plan["units"][0]["suggested_model"] == "sonnet"
    assert plan["units"][0]["suggested_model_confidence"] == 0.0


def test_plan_inline_swarm_auto_model_does_not_affect_agent_or_status(tmp_path: Path) -> None:
    """Auto-model annotation must not touch existing manifest fields/behavior."""
    report = summarize(_corpus())
    plan_inline_swarm(
        tmp_path, ["polish the ui layout"], concurrency=1,
        swarm_id="sanity1", now=_FIXED_NOW, auto_model_report=report,
    )

    import json

    manifest = json.loads(
        (tmp_path / ".onmc" / "swarm" / "sanity1" / "manifest.json").read_text()
    )
    unit = manifest["units"]["unit-0000"]
    assert unit["status"] == "pending"
    assert unit["cost_usd"] == 0.0
    assert unit["verified"] is None
    assert manifest["agent"] == "claude-code-subagent"
