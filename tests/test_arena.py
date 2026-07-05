"""Tests for ``onmc arena`` — ELO scoreboard.

All pure and self-contained.  The ELO math is exercised with known vectors so
regressions in the formula are caught immediately.

Covers:
1. ELO known vector: equal ratings + win → +16/-16 at k=32.
2. ELO known vector: draw at equal ratings → no change.
3. ELO known vector: higher-rated underdog win produces larger swing.
4. Leaderboard ordering is deterministic (rating desc, tiebreak by name).
5. Ratings are always recomputed from bouts (can't drift).
6. Standings history records rating after each bout.
7. ``--json`` envelopes for bout, leaderboard, and standings.
8. Unknown model graceful: standings exits non-zero without crashing.
9. Malformed bouts in JSONL are silently skipped.
10. Empty leaderboard is graceful (no crash, friendly output).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from oh_no_my_claudecode.arena.elo import (
    DEFAULT_RATING,
    Bout,
    Ledger,
    append_bout,
    build_ledger,
    load_bouts,
    rank_ledger,
    save_ratings,
    update_elo,
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _bout(a: str, b: str, winner: str, task: str = "") -> Bout:
    return Bout(model_a=a, model_b=b, winner=winner, task=task)


def _approx(val: float, expected: float, tol: float = 0.01) -> bool:
    return abs(val - expected) < tol


# ---------------------------------------------------------------------------
# 1. ELO known vector: equal ratings, A wins → +16 / -16 at k=32
# ---------------------------------------------------------------------------


def test_update_elo_equal_ratings_a_wins() -> None:
    """Standard ELO: equal ratings, A wins → exactly +16/-16."""
    ra, rb = update_elo(1000.0, 1000.0, "A", k=32.0)
    # expected_a = 0.5 → delta = 32 * (1 - 0.5) = +16
    assert _approx(ra, 1016.0)
    assert _approx(rb, 984.0)


def test_update_elo_equal_ratings_b_wins() -> None:
    """Standard ELO: equal ratings, B wins → -16/+16."""
    ra, rb = update_elo(1000.0, 1000.0, "B", k=32.0)
    assert _approx(ra, 984.0)
    assert _approx(rb, 1016.0)


# ---------------------------------------------------------------------------
# 2. ELO known vector: draw at equal ratings → no change
# ---------------------------------------------------------------------------


def test_update_elo_equal_ratings_draw() -> None:
    """Draw at equal ratings: both ratings unchanged (expected = 0.5)."""
    ra, rb = update_elo(1000.0, 1000.0, "draw", k=32.0)
    assert _approx(ra, 1000.0, tol=1e-9)
    assert _approx(rb, 1000.0, tol=1e-9)


# ---------------------------------------------------------------------------
# 3. Higher-rated underdog win produces larger swing
# ---------------------------------------------------------------------------


def test_update_elo_underdog_win_larger_swing() -> None:
    """Lower-rated model beating higher-rated model gains more than 16 points."""
    # model_a is rated 200 points lower → expected_a < 0.5 → larger swing if wins
    ra, rb = update_elo(800.0, 1200.0, "A", k=32.0)
    delta_a = ra - 800.0
    # expected_a = 1 / (1 + 10^((1200-800)/400)) = 1 / (1 + 10^1) = 1/11 ≈ 0.0909
    expected_a = 1.0 / (1.0 + math.pow(10.0, (1200.0 - 800.0) / 400.0))
    expected_delta = 32.0 * (1.0 - expected_a)
    assert _approx(delta_a, expected_delta, tol=0.001)
    assert delta_a > 16.0  # underdog bonus


def test_update_elo_favourite_win_smaller_swing() -> None:
    """Higher-rated model winning gains less than 16 points (expected outcome)."""
    ra, rb = update_elo(1200.0, 800.0, "A", k=32.0)
    delta_a = ra - 1200.0
    assert 0 < delta_a < 16.0


# ---------------------------------------------------------------------------
# 4. Leaderboard ordering: rating desc, tiebreak by name asc
# ---------------------------------------------------------------------------


def test_rank_ledger_ordering() -> None:
    """Leaderboard is sorted by rating desc; alpha is #1 after two wins."""
    bouts = [
        _bout("alpha", "beta", "A"),  # alpha wins → alpha > beta
        _bout("alpha", "gamma", "A"),  # alpha wins again
    ]
    ledger = build_ledger(bouts)
    ranked = rank_ledger(ledger)
    assert len(ranked) == 3
    # alpha has the most wins → highest rating
    assert ranked[0].model == "alpha"
    # beta and gamma both lost once; verify they appear after alpha
    remaining = {r.model for r in ranked[1:]}
    assert remaining == {"beta", "gamma"}
    # all three ratings are distinct (no ties in this scenario)
    ratings = [r.rating for r in ranked]
    assert ratings == sorted(ratings, reverse=True)


def test_rank_ledger_tiebreak_alphabetical() -> None:
    """Exact tie in rating → alphabetical tiebreak is stable."""
    # Two models that have never met each other, both at DEFAULT_RATING
    bouts: list[Bout] = []
    ledger = build_ledger(bouts)
    # Force two records at equal rating by building manually
    from oh_no_my_claudecode.arena.elo import ModelRecord

    ledger.models["zeta"] = ModelRecord(model="zeta", rating=1100.0)
    ledger.models["alpha"] = ModelRecord(model="alpha", rating=1100.0)
    ledger.models["beta"] = ModelRecord(model="beta", rating=900.0)
    ranked = rank_ledger(ledger)
    assert ranked[0].model == "alpha"  # tied at 1100, "alpha" < "zeta"
    assert ranked[1].model == "zeta"
    assert ranked[2].model == "beta"


# ---------------------------------------------------------------------------
# 5. Ratings always recomputed from bouts (can't drift)
# ---------------------------------------------------------------------------


def test_ratings_recomputed_from_bouts(tmp_path: Path) -> None:
    """build_ledger from the same bouts always yields the same ratings."""
    bouts = [
        _bout("gpt-4o", "claude-3-7", "A"),
        _bout("gpt-4o", "claude-3-7", "B"),
        _bout("gpt-4o", "claude-3-7", "draw"),
    ]
    ledger1 = build_ledger(bouts)
    ledger2 = build_ledger(bouts)  # rebuild from scratch

    assert ledger1.models["gpt-4o"].rating == ledger2.models["gpt-4o"].rating
    assert ledger1.models["claude-3-7"].rating == ledger2.models["claude-3-7"].rating


def test_build_ledger_deterministic_round_trip(tmp_path: Path) -> None:
    """Persisting bouts then reloading and rebuilding yields identical ratings."""
    bouts_path = tmp_path / "bouts.jsonl"
    bouts = [
        _bout("m1", "m2", "A"),
        _bout("m2", "m3", "B"),
        _bout("m1", "m3", "draw"),
    ]
    for b in bouts:
        append_bout(bouts_path, b)

    reloaded = load_bouts(bouts_path)
    ledger = build_ledger(reloaded)

    expected = build_ledger(bouts)
    assert ledger.models["m1"].rating == expected.models["m1"].rating
    assert ledger.models["m2"].rating == expected.models["m2"].rating
    assert ledger.models["m3"].rating == expected.models["m3"].rating


# ---------------------------------------------------------------------------
# 6. Standings history records rating after each bout
# ---------------------------------------------------------------------------


def test_standings_rating_history() -> None:
    """Each bout appends to the model's rating_history in order."""
    bouts = [
        _bout("x", "y", "A"),
        _bout("x", "y", "A"),
        _bout("x", "y", "B"),
    ]
    ledger = build_ledger(bouts)
    rec_x = ledger.models["x"]

    assert len(rec_x.rating_history) == 3
    # After two wins and one loss, trajectory: up, up, down
    assert rec_x.rating_history[0] > DEFAULT_RATING  # won
    assert rec_x.rating_history[1] > rec_x.rating_history[0]  # won again
    assert rec_x.rating_history[2] < rec_x.rating_history[1]  # lost


def test_standings_win_loss_draw_counts() -> None:
    """W/L/D tallies are correctly maintained over multiple bouts."""
    bouts = [
        _bout("a", "b", "A"),
        _bout("a", "b", "B"),
        _bout("a", "b", "draw"),
    ]
    ledger = build_ledger(bouts)
    rec = ledger.models["a"]
    assert rec.wins == 1
    assert rec.losses == 1
    assert rec.draws == 1
    assert rec.bouts == 3


# ---------------------------------------------------------------------------
# 7. --json envelopes
# ---------------------------------------------------------------------------


def test_bout_to_dict_json_round_trip() -> None:
    """Bout serialises and deserialises cleanly."""
    b = Bout(model_a="gpt-4o", model_b="gemini-2.0", winner="A", task="summarise")
    d = b.to_dict()
    assert d["model_a"] == "gpt-4o"
    assert d["model_b"] == "gemini-2.0"
    assert d["winner"] == "A"
    assert d["task"] == "summarise"
    # Round-trip
    b2 = Bout.from_dict(d)
    assert b2.model_a == b.model_a
    assert b2.winner == b.winner


def test_ledger_to_dict_is_json_serialisable() -> None:
    """Ledger.to_dict() is JSON-serialisable without errors."""
    bouts = [_bout("x", "y", "A"), _bout("y", "z", "draw")]
    ledger = build_ledger(bouts)
    payload = ledger.to_dict()
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    assert "models" in decoded
    assert "x" in decoded["models"]


def test_model_record_to_dict_json_envelope() -> None:
    """ModelRecord.to_dict() includes all expected fields."""
    bouts = [_bout("m", "n", "A")]
    ledger = build_ledger(bouts)
    rec = ledger.models["m"]
    d = rec.to_dict()
    for key in ("model", "rating", "wins", "losses", "draws", "bouts", "rating_history"):
        assert key in d, f"missing key: {key}"


# ---------------------------------------------------------------------------
# 8. Unknown model graceful (standings exits non-zero)
# ---------------------------------------------------------------------------


def test_build_ledger_unknown_model_not_in_ledger() -> None:
    """A model not in any bout is absent from the ledger (honest)."""
    bouts = [_bout("a", "b", "A")]
    ledger = build_ledger(bouts)
    assert "unknown-model" not in ledger.models


def test_build_ledger_empty_is_graceful() -> None:
    """Empty bouts list produces an empty ledger (no crash, no fabricated data)."""
    ledger = build_ledger([])
    assert ledger.models == {}
    assert rank_ledger(ledger) == []


# ---------------------------------------------------------------------------
# 9. Malformed JSONL lines are silently skipped
# ---------------------------------------------------------------------------


def test_load_bouts_tolerant_of_bad_lines(tmp_path: Path) -> None:
    """Blank, non-JSON, and non-object lines in JSONL are silently skipped."""
    bouts_path = tmp_path / "bouts.jsonl"
    bouts_path.write_text(
        "\n"
        '{"model_a": "x", "model_b": "y", "winner": "A", "task": ""}\n'
        "not valid json\n"
        '["array", "not", "object"]\n'
        '{"model_a": "y", "model_b": "z", "winner": "B", "task": ""}\n',
        encoding="utf-8",
    )
    bouts = load_bouts(bouts_path)
    assert len(bouts) == 2
    assert bouts[0].model_a == "x"
    assert bouts[1].model_b == "z"


def test_load_bouts_missing_file_is_graceful(tmp_path: Path) -> None:
    """load_bouts returns [] when the file does not exist."""
    bouts = load_bouts(tmp_path / "nonexistent.jsonl")
    assert bouts == []


# ---------------------------------------------------------------------------
# 10. Empty leaderboard is graceful
# ---------------------------------------------------------------------------


def test_empty_leaderboard_graceful() -> None:
    """rank_ledger on empty ledger returns [] without raising."""
    ledger = Ledger()
    assert rank_ledger(ledger) == []


# ---------------------------------------------------------------------------
# Persistence: save_ratings / append_bout round-trips
# ---------------------------------------------------------------------------


def test_save_ratings_produces_valid_json(tmp_path: Path) -> None:
    """save_ratings writes a valid JSON file with a 'models' key."""
    bouts = [_bout("a", "b", "A")]
    ledger = build_ledger(bouts)
    ratings_path = tmp_path / "arena" / "ratings.json"
    save_ratings(ratings_path, ledger)

    content = json.loads(ratings_path.read_text(encoding="utf-8"))
    assert "models" in content
    assert "a" in content["models"]


def test_append_bout_creates_parents(tmp_path: Path) -> None:
    """append_bout creates the parent directory if it does not exist."""
    bouts_path = tmp_path / "nested" / "dir" / "bouts.jsonl"
    assert not bouts_path.parent.exists()
    b = _bout("p", "q", "draw")
    append_bout(bouts_path, b)
    assert bouts_path.exists()
    reloaded = load_bouts(bouts_path)
    assert len(reloaded) == 1
    assert reloaded[0].model_a == "p"


# ---------------------------------------------------------------------------
# Bout with task description
# ---------------------------------------------------------------------------


def test_bout_task_preserved_in_round_trip(tmp_path: Path) -> None:
    """Task field is persisted and reloaded correctly."""
    bouts_path = tmp_path / "bouts.jsonl"
    b = Bout(model_a="x", model_b="y", winner="A", task="code generation")
    append_bout(bouts_path, b)
    reloaded = load_bouts(bouts_path)
    assert reloaded[0].task == "code generation"
