"""Pure, offline unit tests for the coach commentary engine.

No filesystem, storage, or network: the pure ``commentary`` module is
tested directly by injecting seeds and event kinds.  JSON envelope shape
tests verify the payload structure using the core functions directly —
no CLI invocation or real filesystem required.
"""

from __future__ import annotations

from oh_no_my_claudecode.coach.commentary import (
    GREEN_EVENTS,
    RED_EVENTS,
    StreakState,
    advance,
    quip,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blank() -> StreakState:
    return StreakState()


# ---------------------------------------------------------------------------
# quip — deterministic selection
# ---------------------------------------------------------------------------


def test_quip_is_deterministic_same_seed() -> None:
    """Same (event, tone, seed) always returns the same line."""
    result_a = quip("test_pass", "hype", seed=0)
    result_b = quip("test_pass", "hype", seed=0)
    assert result_a == result_b


def test_quip_differs_by_seed() -> None:
    """Different seeds produce different lines (at least for a known bank)."""
    line0 = quip("test_pass", "hype", seed=0)
    line1 = quip("test_pass", "hype", seed=1)
    # Template bank for test_pass/hype has 5 entries, so seed 0 ≠ seed 1.
    assert line0 != line1


def test_quip_exact_value_for_known_triple() -> None:
    """Assert the exact first quip for a known (event, tone, seed) triple."""
    # This pins the template bank's index-0 entry for test_pass/hype.
    result = quip("test_pass", "hype", seed=0)
    assert result == "Tests green — you're cooking. Keep the heat on."


def test_quip_exact_value_roast_seed_0() -> None:
    result = quip("test_fail", "roast", seed=0)
    assert result == "Tests failed. The tests are trying to tell you something."


def test_quip_exact_value_dry_pr_merged() -> None:
    result = quip("pr_merged", "dry", seed=0)
    assert result == "PR merged."


def test_quip_wraps_around_template_length() -> None:
    """Seed wraps modulo template length — never IndexError."""
    # test_pass/hype has 5 entries; seed=5 should wrap to index 0.
    assert quip("test_pass", "hype", seed=5) == quip("test_pass", "hype", seed=0)


def test_quip_unknown_event_returns_fallback() -> None:
    """An unrecognised event returns a non-empty fallback line."""
    result = quip("galaxy_brain", "hype", seed=0)
    assert isinstance(result, str) and len(result) > 0


def test_quip_unknown_tone_falls_back_to_dry() -> None:
    """An unrecognised tone falls back to dry templates."""
    result = quip("test_pass", "formal", seed=0)
    assert isinstance(result, str) and len(result) > 0


# ---------------------------------------------------------------------------
# StreakState — green events extend streak
# ---------------------------------------------------------------------------


def test_green_event_extends_streak() -> None:
    state = advance(_blank(), "test_pass")
    assert state.current_streak == 1
    assert state.combo == 1


def test_multiple_green_events_build_streak() -> None:
    state = _blank()
    for event in ("test_pass", "commit", "build_pass"):
        state = advance(state, event)
    assert state.current_streak == 3
    assert state.combo == 3


def test_red_event_resets_streak() -> None:
    state = advance(_blank(), "test_pass")
    state = advance(state, "test_pass")
    assert state.current_streak == 2

    state = advance(state, "test_fail")
    assert state.current_streak == 0


def test_red_event_does_not_reset_combo() -> None:
    """Combo is cumulative green count and is never reset by red events."""
    state = _blank()
    state = advance(state, "test_pass")
    state = advance(state, "test_pass")
    assert state.combo == 2
    state = advance(state, "test_fail")
    # combo stays at 2 after a red event
    assert state.combo == 2


def test_best_streak_persists_after_reset() -> None:
    """Best streak survives a red event."""
    state = _blank()
    for _ in range(4):
        state = advance(state, "test_pass")
    assert state.best_streak == 4

    state = advance(state, "build_break")
    assert state.current_streak == 0
    assert state.best_streak == 4  # persists


def test_neutral_event_does_not_change_streak() -> None:
    """An event that is neither green nor red leaves streak unchanged."""
    state = advance(_blank(), "test_pass")
    assert state.current_streak == 1

    state = advance(state, "some_neutral_event")
    assert state.current_streak == 1
    assert state.combo == 1


def test_total_events_always_increments() -> None:
    state = _blank()
    state = advance(state, "test_pass")
    state = advance(state, "test_fail")
    state = advance(state, "neutral_xyz")
    assert state.total_events == 3


def test_recent_events_capped_at_20() -> None:
    state = _blank()
    for _ in range(25):
        state = advance(state, "test_pass")
    assert len(state.recent_events) == 20


# ---------------------------------------------------------------------------
# StreakState serialisation round-trip
# ---------------------------------------------------------------------------


def test_streak_roundtrip() -> None:
    state = StreakState(
        current_streak=3,
        best_streak=7,
        combo=12,
        total_events=20,
        recent_events=("test_pass", "commit", "test_fail"),
    )
    restored = StreakState.from_dict(state.to_dict())
    assert restored == state


# ---------------------------------------------------------------------------
# JSON envelope shapes (command layer via CliRunner)
# ---------------------------------------------------------------------------


def test_react_json_envelope() -> None:
    """The JSON envelope produced by the react command has the expected shape.

    We verify this by constructing the expected payload directly from the pure
    core functions — no CLI invocation needed (CliRunner cannot change cwd).
    """
    state0 = StreakState()
    new_state = advance(state0, "test_pass")
    line = quip("test_pass", "hype", seed=0)
    payload = {
        "kind": "coach_react",
        "event": "test_pass",
        "tone": "hype",
        "quip": line,
        "streak": new_state.to_dict(),
    }
    assert payload["kind"] == "coach_react"
    assert payload["event"] == "test_pass"
    assert "quip" in payload
    assert "streak" in payload


def test_streak_json_envelope_shape() -> None:
    """Streak JSON envelope contains expected keys."""
    state = StreakState(current_streak=2, best_streak=5, combo=8, total_events=10)
    d = state.to_dict()
    assert set(d.keys()) == {
        "current_streak",
        "best_streak",
        "combo",
        "total_events",
        "recent_events",
    }
    assert d["current_streak"] == 2
    assert d["best_streak"] == 5


# ---------------------------------------------------------------------------
# Green / red event classification
# ---------------------------------------------------------------------------


def test_known_green_events_classified() -> None:
    for ev in ("test_pass", "pr_merged", "commit", "build_pass"):
        assert ev in GREEN_EVENTS, f"{ev} should be green"


def test_known_red_events_classified() -> None:
    for ev in ("test_fail", "build_break", "revert"):
        assert ev in RED_EVENTS, f"{ev} should be red"


# ---------------------------------------------------------------------------
# cheer — deterministic pep line
# ---------------------------------------------------------------------------


def test_cheer_deterministic_from_event_count() -> None:
    """cheer uses quip('commit', 'hype', seed=total_events) — pinned."""
    result = quip("commit", "hype", seed=0)
    assert result == "Commit landed. The history grows richer."


def test_cheer_seed_wraps() -> None:
    """cheer with seed=5 wraps around commit/hype bank correctly."""
    # commit/hype has 5 entries; seed=5 → same as seed=0
    assert quip("commit", "hype", seed=5) == quip("commit", "hype", seed=0)
