"""Tests for ``onmc vibe`` — ambient agent-mood HUD.

Coverage
--------
- compute_mood: high streak + praises → ON_FIRE.
- compute_mood: corrections-heavy → STRUGGLING.
- compute_mood: deterministic for given inputs.
- compute_mood: graceful when a source absent → partial mood from remaining.
- compute_mood: all-empty inputs → MEH (neutral default).
- compute_mood: high level without streak → CRUISING.
- compute_mood: streak >= 2, no whip data → CRUISING.
- render: output contains component readout labels.
- render_json: envelope has required keys.
- CLI ``onmc vibe --json``: JSON envelope shape.
- CLI ``onmc vibe mood --json``: mood-only JSON shape.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.vibe.hud import (
    Mood,
    VibeState,
    compute_mood,
    render,
    render_json,
)

_RUNNER = CliRunner()


# ---------------------------------------------------------------------------
# compute_mood — threshold tests
# ---------------------------------------------------------------------------


def test_compute_mood_on_fire_high_streak_and_praises() -> None:
    """High streak + praises ratio >= 0.6 → ON_FIRE."""
    mood, score = compute_mood(streak=6, praises=4, corrections=1, level=3)
    assert mood == Mood.ON_FIRE
    assert score > 0.7


def test_compute_mood_on_fire_high_streak_no_whip() -> None:
    """High streak with no whip data still triggers ON_FIRE."""
    mood, score = compute_mood(streak=7, praises=None, corrections=None, level=None)
    assert mood == Mood.ON_FIRE


def test_compute_mood_struggling_corrections_heavy() -> None:
    """More corrections than praises → STRUGGLING."""
    mood, score = compute_mood(streak=0, praises=2, corrections=5, level=1)
    assert mood == Mood.STRUGGLING
    assert score < 0.5


def test_compute_mood_struggling_zero_streak_with_corrections() -> None:
    """Streak reset to 0 while corrections > 0 → STRUGGLING."""
    mood, _score = compute_mood(streak=0, praises=0, corrections=3, level=2)
    assert mood == Mood.STRUGGLING


def test_compute_mood_all_none_returns_meh() -> None:
    """All-empty inputs → MEH (neutral default)."""
    mood, score = compute_mood(streak=None, praises=None, corrections=None, level=None)
    assert mood == Mood.MEH
    assert score == 0.5


def test_compute_mood_deterministic_same_inputs() -> None:
    """Same inputs always return the same mood and score."""
    result_a = compute_mood(streak=3, praises=5, corrections=1, level=4)
    result_b = compute_mood(streak=3, praises=5, corrections=1, level=4)
    assert result_a == result_b


def test_compute_mood_cruising_from_streak() -> None:
    """streak >= 2, no whip data → CRUISING."""
    mood, score = compute_mood(streak=3, praises=None, corrections=None, level=None)
    assert mood == Mood.CRUISING
    assert 0.5 <= score < 0.7


def test_compute_mood_cruising_from_level() -> None:
    """level >= 5 with no streak or whip → CRUISING."""
    mood, score = compute_mood(streak=None, praises=None, corrections=None, level=8)
    assert mood == Mood.CRUISING
    assert 0.5 <= score < 0.7


def test_compute_mood_cruising_from_praise_ratio() -> None:
    """praise_ratio >= 0.5 with >= 2 total rewards → CRUISING."""
    mood, _score = compute_mood(streak=1, praises=3, corrections=2, level=2)
    assert mood == Mood.CRUISING


def test_compute_mood_partial_only_streak() -> None:
    """Only streak provided (coach only, whip + quest absent) — mood from streak."""
    mood, _score = compute_mood(streak=1, praises=None, corrections=None, level=None)
    # streak=1 < 2 → not cruising from streak; no other signal → MEH
    assert mood == Mood.MEH


def test_compute_mood_partial_only_level_low() -> None:
    """Only low level provided, no streak or whip → MEH."""
    mood, _score = compute_mood(streak=None, praises=None, corrections=None, level=3)
    assert mood == Mood.MEH


# ---------------------------------------------------------------------------
# render — HUD string
# ---------------------------------------------------------------------------


def test_render_contains_component_labels() -> None:
    """Rendered HUD contains all expected readout labels."""
    state = VibeState(streak=4, praises=3, corrections=1, level=5, total_xp=200, xp_to_next=50)
    output = render(state)
    assert "coach streak" in output
    assert "whip praises" in output
    assert "corrections" in output
    assert "quest level" in output
    assert "XP" in output


def test_render_shows_na_when_absent() -> None:
    """Absent sources render as 'n/a'."""
    state = VibeState()
    output = render(state)
    assert "n/a" in output


def test_render_shows_mood_emoji() -> None:
    """ON_FIRE state renders the fire emoji."""
    state = VibeState(streak=8, praises=5, corrections=1, level=10)
    output = render(state)
    assert "\U0001f525" in output  # 🔥


def test_render_meh_emoji_when_empty() -> None:
    """All-empty state renders MEH emoji."""
    state = VibeState()
    output = render(state)
    assert "\U0001f610" in output  # 😐


# ---------------------------------------------------------------------------
# render_json
# ---------------------------------------------------------------------------


def test_render_json_envelope_keys() -> None:
    """JSON envelope contains all required keys."""
    state = VibeState(streak=2, praises=3, corrections=1, level=4)
    envelope = render_json(state)
    assert envelope["kind"] == "vibe"
    assert "mood" in envelope
    assert "emoji" in envelope
    assert "score" in envelope
    assert "caption" in envelope
    assert "components" in envelope


def test_render_json_components_match_state() -> None:
    """JSON envelope components reflect the input VibeState."""
    state = VibeState(streak=5, praises=7, corrections=2, level=6, total_xp=350)
    envelope = render_json(state)
    comps = envelope["components"]
    assert comps["streak"] == 5
    assert comps["praises"] == 7
    assert comps["corrections"] == 2
    assert comps["level"] == 6
    assert comps["total_xp"] == 350


# ---------------------------------------------------------------------------
# CLI — JSON envelope shapes
# ---------------------------------------------------------------------------


def test_cli_vibe_json_envelope() -> None:
    """``onmc vibe --json`` returns a valid JSON envelope with required keys."""
    result = _RUNNER.invoke(app, ["vibe", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "vibe"
    assert data["mood"] in {"on_fire", "cruising", "meh", "struggling"}
    assert isinstance(data["score"], float)
    assert "caption" in data
    assert "components" in data


def test_cli_vibe_mood_json() -> None:
    """``onmc vibe mood --json`` returns a compact mood-only JSON envelope."""
    result = _RUNNER.invoke(app, ["vibe", "mood", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "vibe_mood"
    assert data["mood"] in {"on_fire", "cruising", "meh", "struggling"}
    assert isinstance(data["score"], float)
    assert "emoji" in data


def test_cli_vibe_plain_text() -> None:
    """``onmc vibe`` (plain) produces non-empty output without crashing."""
    result = _RUNNER.invoke(app, ["vibe"])
    assert result.exit_code == 0, result.output
    assert len(result.output.strip()) > 0
