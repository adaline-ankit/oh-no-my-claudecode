"""Tests for the ``onmc scorecard`` aggregator.

The aggregation logic is exercised purely by injecting the four signal readers
into :func:`build_scorecard` — no storage, ledger, or receipts required. We prove:

- a fresh/empty repo (every reader returns ``None``) yields an all-``None``
  scorecard with explanatory notes and *never raises*;
- a reader that *raises* degrades to ``None`` + a note, not a crash;
- populated readers flow their values through to the scorecard and into the
  rendered Markdown;
- rendering is deterministic.
"""

from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.scorecard.scorecard import (
    Scorecard,
    build_scorecard,
    render_markdown,
    render_summary,
)

# A sentinel repo root — the injected readers ignore it, so it need not exist.
_REPO = Path(__file__).parent / "does-not-need-to-exist"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def test_all_signals_none_is_graceful() -> None:
    """Every signal unavailable → all-None card + one note each, no exception."""
    card = build_scorecard(
        _REPO,
        readiness_reader=lambda _: None,
        top_agent_reader=lambda _: None,
        best_model_reader=lambda _: None,
        memory_graph_reader=lambda _: None,
    )
    assert card.readiness is None
    assert card.top_agent is None
    assert card.top_agent_trust is None
    assert card.best_model is None
    assert card.memory_entities is None
    assert card.memory_edges is None
    # One "n/a" note per signal.
    assert len(card.notes) == 4
    assert all("n/a" in note for note in card.notes)


def test_raising_readers_degrade_not_crash() -> None:
    """A reader that raises must be caught and turned into an n/a note."""

    def _boom(_: Path) -> object:
        raise RuntimeError("storage exploded")

    card = build_scorecard(
        _REPO,
        readiness_reader=_boom,  # type: ignore[arg-type]
        top_agent_reader=_boom,  # type: ignore[arg-type]
        best_model_reader=_boom,  # type: ignore[arg-type]
        memory_graph_reader=_boom,  # type: ignore[arg-type]
    )
    assert card == Scorecard(notes=card.notes)  # all fields None
    assert len(card.notes) == 4
    assert all("storage exploded" in note for note in card.notes)


def test_build_scorecard_on_fresh_repo_does_not_crash(tmp_path: Path) -> None:
    """The real readers on an empty tmp dir must degrade, never raise."""
    card = build_scorecard(tmp_path)
    # Nothing is initialised, so every signal should be n/a (None) with a note.
    assert card.readiness is None
    assert card.top_agent is None
    assert card.best_model is None
    assert card.memory_entities is None
    assert card.notes  # at least one explanatory note


# ---------------------------------------------------------------------------
# Populated signals flow through
# ---------------------------------------------------------------------------


def _populated_card() -> Scorecard:
    return build_scorecard(
        _REPO,
        readiness_reader=lambda _: 87,
        top_agent_reader=lambda _: ("agent-alpha", 0.9123),
        best_model_reader=lambda _: "claude-opus-4-8",
        memory_graph_reader=lambda _: (42, 108),
    )


def test_populated_signals_populate_fields() -> None:
    card = _populated_card()
    assert card.readiness == 87
    assert card.top_agent == "agent-alpha"
    assert card.top_agent_trust == 0.9123
    assert card.best_model == "claude-opus-4-8"
    assert card.memory_entities == 42
    assert card.memory_edges == 108
    assert card.notes == []  # nothing degraded


def test_partial_signals_mix_values_and_notes() -> None:
    """A mix of present and absent signals populates some fields + notes others."""
    card = build_scorecard(
        _REPO,
        readiness_reader=lambda _: 55,
        top_agent_reader=lambda _: None,
        best_model_reader=lambda _: None,
        memory_graph_reader=lambda _: (3, 1),
    )
    assert card.readiness == 55
    assert card.memory_entities == 3
    assert card.memory_edges == 1
    assert card.top_agent is None
    assert card.best_model is None
    assert len(card.notes) == 2


def test_to_dict_roundtrips_fields() -> None:
    card = _populated_card()
    d = card.to_dict()
    assert d == {
        "readiness": 87,
        "top_agent": "agent-alpha",
        "top_agent_trust": 0.9123,
        "best_model": "claude-opus-4-8",
        "memory_entities": 42,
        "memory_edges": 108,
        "notes": [],
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_markdown_contains_populated_values() -> None:
    md = render_markdown(_populated_card())
    assert "## onmc scorecard" in md
    assert "87/100" in md
    assert "agent-alpha" in md
    assert "0.9123" in md
    assert "claude-opus-4-8" in md
    assert "42 entities, 108 edges" in md
    # shields badge present (assert the /badge/ path, not the bare host — a host
    # substring check trips CodeQL's incomplete-URL-sanitization rule)
    assert "/badge/" in md


def test_markdown_shows_na_for_missing() -> None:
    card = build_scorecard(
        _REPO,
        readiness_reader=lambda _: None,
        top_agent_reader=lambda _: None,
        best_model_reader=lambda _: None,
        memory_graph_reader=lambda _: None,
    )
    md = render_markdown(card)
    assert "n/a" in md
    assert "Unavailable signals" in md


def test_markdown_is_deterministic() -> None:
    card = _populated_card()
    assert render_markdown(card) == render_markdown(card)


def test_render_summary_uses_console_stub() -> None:
    """render_summary should print exactly once to the injected console."""

    captured: list[object] = []

    class _Stub:
        def print(self, renderable: object) -> None:
            captured.append(renderable)

    render_summary(_populated_card(), _Stub())
    assert len(captured) == 1
