"""Tests for onmc autoroute: suggest_model and suggest_from_repo.

All inputs are built in-memory — either :class:`FlywheelReport` objects
constructed directly, or synthetic receipt dicts routed through the flywheel's
own :func:`summarize` (no DB, no files, no clock).  Every assertion is
deterministic.
"""

from __future__ import annotations

from typing import Any

from oh_no_my_claudecode.autoroute.autoroute import suggest_from_repo, suggest_model
from oh_no_my_claudecode.flywheel.analyze import (
    FlywheelReport,
    KeywordStat,
    ModelStat,
    summarize,
)

# ---------------------------------------------------------------------------
# Helpers — build a corpus with a clear per-keyword winner + overall winner
# ---------------------------------------------------------------------------


def _receipt(
    *,
    model: str,
    verified: bool,
    goal: str,
    cost_usd: float | None = 0.10,
    wall_seconds: float = 60.0,
) -> dict[str, Any]:
    """Minimal trajectory receipt dict the flywheel's summarize accepts."""
    return {
        "model": model,
        "verified": verified,
        "goal": goal,
        "cost_usd": cost_usd,
        "wall_seconds": wall_seconds,
    }


def _corpus() -> list[dict[str, Any]]:
    """A corpus where:

    - goals about 'parser' are reliably won by opus (3/3 verified),
    - goals about 'ui'/'css' are reliably won by sonnet,
    - overall, sonnet has the most verified runs (the overall best model).
    """
    receipts: list[dict[str, Any]] = []
    # opus dominates 'parser' goals: 3/3 verified.
    for _ in range(3):
        receipts.append(_receipt(model="opus", verified=True, goal="refactor the parser module"))
    # haiku tried 'parser' once and failed — should not win the keyword.
    receipts.append(_receipt(model="haiku", verified=False, goal="rewrite parser tokenizer"))
    # sonnet dominates 'ui' goals and racks up overall volume.
    for _ in range(5):
        receipts.append(_receipt(model="sonnet", verified=True, goal="polish the ui layout"))
    receipts.append(_receipt(model="sonnet", verified=True, goal="style the css theme"))
    return receipts


# ---------------------------------------------------------------------------
# Keyword-match path
# ---------------------------------------------------------------------------


def test_keyword_match_picks_keyword_winner_with_high_confidence() -> None:
    report = summarize(_corpus())
    s = suggest_model(report, "improve the parser error handling")
    assert s.model == "opus"
    assert s.basis.startswith("goal-keyword 'parser'")
    assert s.confidence == 1.0  # opus verified 3/3 for 'parser'
    assert "opus" in s.rationale


def test_keyword_confidence_exceeds_overall_confidence() -> None:
    """A keyword hit should be at least as confident as the overall fallback."""
    report = summarize(_corpus())
    kw = suggest_model(report, "the parser needs work")
    overall = suggest_model(report, "something totally unrelated zzz")
    assert kw.basis.startswith("goal-keyword")
    assert overall.basis.startswith("overall best")
    assert kw.confidence >= overall.confidence


# ---------------------------------------------------------------------------
# Overall-best fallback path
# ---------------------------------------------------------------------------


def test_no_keyword_match_falls_back_to_overall_best() -> None:
    report = summarize(_corpus())
    s = suggest_model(report, "deploy the release pipeline widget")
    assert s.model == "sonnet"  # overall best by verified volume
    assert s.basis.startswith("overall best")
    assert 0.0 < s.confidence <= 0.6  # moderate, capped


def test_overall_confidence_is_capped() -> None:
    """Even a 100%-verified overall model is capped below full confidence."""
    report = FlywheelReport(
        total=4,
        verified_total=4,
        by_model=[
            ModelStat(
                model="opus",
                runs=4,
                verified=4,
                verified_rate=1.0,
                avg_cost=0.1,
                avg_wall=10.0,
            )
        ],
        by_goal_keyword=[],
        best=ModelStat(
            model="opus", runs=4, verified=4, verified_rate=1.0, avg_cost=0.1, avg_wall=10.0
        ),
        worst=None,
    )
    s = suggest_model(report, "no matching keyword here")
    assert s.model == "opus"
    assert s.confidence == 0.6


# ---------------------------------------------------------------------------
# Insufficient-data path
# ---------------------------------------------------------------------------


def test_empty_report_returns_default_with_zero_confidence() -> None:
    report = summarize([])
    s = suggest_model(report, "anything")
    assert s.model == "sonnet"
    assert s.confidence == 0.0
    assert s.basis == "insufficient data"


def test_default_model_is_honored() -> None:
    report = summarize([])
    s = suggest_model(report, "anything", default_model="haiku")
    assert s.model == "haiku"
    assert s.confidence == 0.0
    assert s.basis == "insufficient data"


def test_below_min_samples_is_insufficient() -> None:
    # Two receipts total — below MIN_SAMPLES (3) — no keyword or overall pick.
    receipts = [
        _receipt(model="opus", verified=True, goal="refactor the parser"),
        _receipt(model="opus", verified=True, goal="refactor the parser again"),
    ]
    report = summarize(receipts)
    s = suggest_model(report, "refactor the parser")
    assert s.basis == "insufficient data"
    assert s.confidence == 0.0


def test_keyword_below_min_samples_falls_through() -> None:
    """A keyword with fewer than min_samples runs must not win on its own."""
    report = summarize(_corpus())
    # 'parser' has 4 runs in the corpus; require 5 → keyword path must not fire.
    s = suggest_model(report, "refactor the parser", min_samples=5)
    assert not s.basis.startswith("goal-keyword")


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_deterministic_same_inputs_same_suggestion() -> None:
    report = summarize(_corpus())
    a = suggest_model(report, "improve the parser")
    b = suggest_model(report, "improve the parser")
    assert a == b


def test_keyword_winner_is_deterministic_across_equal_reports() -> None:
    report1 = summarize(_corpus())
    report2 = summarize(list(reversed(_corpus())))
    a = suggest_model(report1, "the parser module")
    b = suggest_model(report2, "the parser module")
    assert a.model == b.model == "opus"
    assert a.confidence == b.confidence


# ---------------------------------------------------------------------------
# suggest_from_repo wrapper (no receipts on disk → insufficient data)
# ---------------------------------------------------------------------------


def test_suggest_from_repo_no_receipts_returns_default(tmp_path: Any) -> None:
    s = suggest_from_repo(tmp_path, "anything at all", default_model="sonnet")
    assert s.model == "sonnet"
    assert s.confidence == 0.0
    assert s.basis == "insufficient data"


# ---------------------------------------------------------------------------
# Directly-constructed KeywordStat (bypassing summarize) still routes correctly
# ---------------------------------------------------------------------------


def test_direct_keyword_stat_report() -> None:
    report = FlywheelReport(
        total=6,
        verified_total=4,
        by_model=[
            ModelStat(
                model="opus", runs=3, verified=3, verified_rate=1.0, avg_cost=0.2, avg_wall=30.0
            ),
        ],
        by_goal_keyword=[
            KeywordStat(
                keyword="migration",
                runs=3,
                verified=3,
                verified_rate=1.0,
                avg_cost=0.2,
                avg_wall=30.0,
                best_model="opus",
                best_model_verified=3,
                best_model_runs=3,
                best_model_avg_cost=0.2,
            )
        ],
        best=ModelStat(
            model="opus", runs=3, verified=3, verified_rate=1.0, avg_cost=0.2, avg_wall=30.0
        ),
        worst=None,
    )
    s = suggest_model(report, "run the database migration")
    assert s.model == "opus"
    assert s.basis.startswith("goal-keyword 'migration'")
    assert s.confidence == 1.0
